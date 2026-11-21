"""Trim each real source, normalize audio/video, concatenate, export an edit list."""
import csv
import json
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from model import load_json, save_json, stamp, under


def ffmpeg_path():
    executable=shutil.which('ffmpeg')
    if executable:return executable
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(command, timeout=900):
    process=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=timeout)
    if process.returncode:
        raise RuntimeError('视频处理失败，请检查源视频和磁盘空间。')
    return process


def probe(path):
    result=subprocess.run([ffmpeg_path(),'-hide_banner','-i',str(path)],capture_output=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=30)
    output=result.stderr.decode('utf-8',errors='replace')
    match=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',output)
    if not match or not re.search(r'Stream .*Video:',output):raise ValueError('素材无法解码。')
    duration=int(match[1])*3600+int(match[2])*60+float(match[3])
    return {'duration':duration,'audio':bool(re.search(r'Stream .*Audio:',output))}


def format_srt_time(seconds):
    total_ms = max(0, round(float(seconds) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _parse_time_token(token):
    token = str(token).strip()
    if ':' in token:
        parts = [float(x) for x in token.split(':')]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return float(token)


def extract_unit_dialogues(unit):
    if not isinstance(unit, dict):
        return []
    events = unit.get('dialogue_events')
    cues = []
    if isinstance(events, list) and events:
        for ev in events:
            if not isinstance(ev, dict):
                continue
            try:
                start_s = float(ev['start_s'])
                end_s = float(ev['end_s'])
            except (KeyError, TypeError, ValueError):
                continue
            text = str(ev.get('text') or ev.get('line') or '').strip()
            if text and end_s > start_s:
                cues.append((start_s, end_s, text))
        if cues:
            return cues
    raw_lines = unit.get('dialogue')
    if isinstance(raw_lines, list):
        pattern = re.compile(r'^\s*(\d+(?::\d+)*(?:\.\d+)?)\s*[–—\-~到至]\s*(\d+(?::\d+)*(?:\.\d+)?)\s*秒?\s*[，,:：]?\s*(.+)$')
        for line in raw_lines:
            if not isinstance(line, str):
                continue
            m = pattern.match(line.strip())
            if not m:
                continue
            try:
                start_s = _parse_time_token(m.group(1))
                end_s = _parse_time_token(m.group(2))
            except ValueError:
                continue
            body = m.group(3).strip()
            speaker_match = re.match(r'^[^：:，。！？“"\s]{1,12}[：:]\s*(.+)$', body)
            if speaker_match:
                body = speaker_match.group(1).strip()
            if body and end_s > start_s:
                cues.append((start_s, end_s, body))
    return cues


def build_srt(studio, data):
    mix = studio.validate_mix(data)
    if not mix['clips']:
        raise ValueError('请先将至少一个片段加入时间轴。')
    episode_units = {}
    cues = []
    offset = 0.0
    for clip in mix['clips']:
        video = studio.video(clip['video_id'])
        eid = video.get('episode_id')
        uid = video.get('unit_id')
        start = float(clip['start'])
        end = float(clip['end'])
        if eid and eid not in episode_units:
            try:
                ep = studio.episode(eid)
                episode_units[eid] = {u.get('id'): u for u in ep.get('units', [])}
            except Exception:
                episode_units[eid] = {}
        unit = episode_units.get(eid, {}).get(uid) if eid and uid else None
        for d_start, d_end, text in extract_unit_dialogues(unit):
            s = max(start, d_start)
            e = min(end, d_end)
            if e - s >= 0.05:
                cues.append((offset + (s - start), offset + (e - start), text))
        offset += (end - start)
    blocks = [f'{idx}\n{format_srt_time(s)} --> {format_srt_time(e)}\n{text}\n' for idx, (s, e, text) in enumerate(cues, 1)]
    name = re.sub(r'[\\/:*?"<>|]+', '_', mix.get('name') or '字幕').strip() or '字幕'
    return {'srt': '\n'.join(blocks), 'count': len(cues), 'filename': name + '.srt'}


class Exporter:
    def __init__(self,studio):
        self.studio=studio;self.lock=threading.Lock();self.active=None
        for p in studio.exports_dir.glob('*/导出状态.json'):
            state=load_json(p)
            if state['state'] in ('queued','running'):
                state.update(state='interrupted',error='服务中断，源素材与方案保留，可重新导出。');save_json(p,state)

    def list(self):
        return [load_json(p) for p in sorted(self.studio.exports_dir.glob('*/导出状态.json'),reverse=True)]

    def start(self,data):
        mix=self.studio.validate_mix(data)
        if not mix['clips']:raise ValueError('请先将至少一个片段加入时间轴。')
        with self.lock:
            if self.active:raise ValueError('已有视频正在导出，请等待完成。')
            eid='export-'+uuid.uuid4().hex[:16];directory=self.studio.exports_dir/eid;directory.mkdir()
            state={'id':eid,'name':mix['name'],'state':'queued','completed':0,'total':len(mix['clips']),'created_at':stamp()}
            save_json(directory/'导出状态.json',state);save_json(directory/'剪辑方案.json',mix)
            self.active=eid
            threading.Thread(target=self.work,args=(directory,mix,state),daemon=True).start()
            return state

    def work(self,directory,mix,state):
        try:
            state['state']='running';save_json(directory/'导出状态.json',state)
            files=[]; manifest=[]; ffmpeg=ffmpeg_path();duration=0
            for index,clip in enumerate(mix['clips']):
                video=self.studio.video(clip['video_id']);source=under(self.studio.root,video['path']);meta=probe(source)
                start=clip['start'];end=clip['end']
                if end > meta['duration']+0.15:raise ValueError(f'片段 {index+1} 超过真实视频时长，请缩短后重新导出。')
                length=end-start;target=directory/f'clip-{index:03d}.mp4'
                command=[ffmpeg,'-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(source)]
                if not meta['audio']:command+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                command+=['-t',str(length),'-map','0:v:0','-map','0:a:0' if meta['audio'] else '1:a:0',
                          '-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
                          '-af','aresample=48000,apad','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',
                          '-c:a','aac','-ac','2','-ar','48000','-b:a','192k','-movflags','+faststart',str(target)]
                run(command);files.append(target);duration+=length
                manifest.append([index+1,video['request_id'],video['path'],start,end,round(length,3)])
                state['completed']=index+1;save_json(directory/'导出状态.json',state)
            listing=directory/'concat.txt';listing.write_text(''.join("file '"+p.name+"'\n" for p in files),encoding='utf-8')
            output=directory/'成片.mp4'
            run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','1','-i',str(listing),'-c','copy','-movflags','+faststart',str(output)])
            actual=probe(output)['duration']
            if abs(actual-duration)>max(0.5,len(files)*0.07):raise ValueError('导出时长校验失败，请重新导出。')
            with (directory/'剪辑清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f);writer.writerow(['顺序','视频版本','源文件','入点秒','出点秒','采用秒数']);writer.writerows(manifest)
            state.update(state='done',duration=round(actual,3),video='/exports/'+state['id']+'/成片.mp4',manifest='/exports/'+state['id']+'/剪辑清单.csv')
            try:
                srt_result = build_srt(self.studio, mix)
                if srt_result['count'] > 0:
                    (directory/'字幕.srt').write_text(srt_result['srt'], encoding='utf-8')
                    state['subtitle'] = '/exports/'+state['id']+'/字幕.srt'
            except Exception:
                pass
            # Remove only known intermediate files in this exact export directory.
            for p in files:p.unlink()
            listing.unlink()
        except Exception as error:
            state.update(state='failed',error=str(error) if isinstance(error,ValueError) else '导出失败，请检查视频是否可播放、依赖与磁盘空间后重试。')
        finally:
            save_json(directory/'导出状态.json',state)
            with self.lock:self.active=None
