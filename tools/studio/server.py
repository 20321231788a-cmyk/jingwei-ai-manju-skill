"""Loopback-only production viewer; no agent-queue control endpoints."""
import argparse
import json
import mimetypes
import os
import re
import secrets
import threading
import webbrowser
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from exporter import Exporter
from model import Studio, load_json, studio_config, under
from regeneration import Regenerator

HERE=Path(__file__).resolve().parent


def byte_range(header,size):
    if not header:return 0,size-1,False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
    if not match or not any(match.groups()):raise ValueError('无效 Range')
    first,last=match.groups()
    if first:
        start=int(first);end=min(int(last),size-1) if last else size-1
    else:
        length=int(last)
        if length<=0:raise ValueError('无效 Range')
        start=max(0,size-length);end=size-1
    if start<0 or start>=size or end<start:raise ValueError('Range 越界')
    return start,end,True


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,studio):
        self.studio=studio;self.csrf=secrets.token_urlsafe(32);self.exporter=Exporter(studio)
        super().__init__(address,Handler)


class Handler(BaseHTTPRequestHandler):
    server_version='MoonlightStudio/1.0'
    def log_message(self,*args):pass  # Request URLs and bodies never enter logs.

    def local(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def common(self,kind,cache_control='no-store'):
        self.send_header('Content-Type',kind)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('X-Frame-Options','SAMEORIGIN')
        self.send_header('Cache-Control',cache_control)

    def json(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.common('application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def html(self, content):
        body=content.encode('utf-8')
        self.send_response(200);self.common('text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def file(self,path):
        if not path.is_file():return self.json({'error':'文件不存在。'},404)
        st=path.stat();size=st.st_size
        cacheable=not self.headers.get('Range') and path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif','.svg','.js','.css')
        etag=f'"{st.st_mtime_ns:x}-{size:x}"' if cacheable else None
        if etag and self.headers.get('If-None-Match')==etag:
            self.send_response(304);self.send_header('ETag',etag);self.send_header('Cache-Control','private, max-age=0, must-revalidate');self.send_header('Content-Length','0');self.end_headers();return
        try:start,end,partial=byte_range(self.headers.get('Range'),size)
        except ValueError:
            self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
        self.send_response(206 if partial else 200)
        kind=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix in ('.html','.js','.css','.srt'):kind=('text/plain' if path.suffix=='.srt' else kind)+'; charset=utf-8'
        self.common(kind,'private, max-age=0, must-revalidate' if etag else 'no-store')
        if etag:self.send_header('ETag',etag)
        self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
        if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command=='HEAD':return
        with path.open('rb') as f:
            f.seek(start);remaining=end-start+1
            while remaining>0:
                block=f.read(min(1024*1024,remaining))
                if not block:break
                self.wfile.write(block);remaining-=len(block)

    def do_HEAD(self):self.do_GET()

    def do_GET(self):
        if not self.local():return self.json({'error':'仅允许本机访问。'},403)
        path=unquote(urlsplit(self.path).path)
        try:
            s=self.server.studio
            if path=='/api/bootstrap':return self.json({'csrf':self.server.csrf,'profiles':s.profiles(),'workspace':str(s.root),'project':s.project or '','protocols':['openai-video-v1','scenora-v1','wan-portal-v1','sparkcine-v1','rb-v1','doubao-canvas-v1']})
            if path=='/preview':
                preview=(s.root/'看板样式预览.html').read_text(encoding='utf-8')
                return self.html(preview.replace('.agents/skills/h3-storyboard-director/assets/character-reference-layout-r2.png','/preview-reference.png'))
            if path=='/preview-reference.png':return self.file(s.root/'.agents/skills/h3-storyboard-director/assets/character-reference-layout-r2.png')
            if path=='/api/state':return self.json(s.snapshot())
            if path=='/api/mixes':return self.json(load_json(s.mix_file))
            if path=='/api/assets':return self.json(s.assets())
            if path=='/api/annotations':return self.json(s.annotations())
            if path=='/api/profiles':return self.json(s.profiles())
            if path=='/api/exports':return self.json(self.server.exporter.list())
            if path.startswith('/api/episode/'):return self.json(s.episode(path.rsplit('/',1)[1]))
            if path.startswith('/media/'):
                return self.file(under(s.root,s.video(path.rsplit('/',1)[1])['path']))
            if path.startswith('/exports/'):
                parts=path.split('/')
                if len(parts)!=4 or not re.fullmatch(r'export-[a-f0-9]{16}',parts[2]) or parts[3] not in ('成片.mp4','剪辑清单.csv','字幕.srt'):
                    raise ValueError('导出路径无效。')
                state=load_json(s.exports_dir/parts[2]/'导出状态.json')
                if state['state']!='done':raise ValueError('导出尚未完成。')
                return self.file(s.exports_dir/parts[2]/parts[3])
            if path.startswith('/board/'):
                ep=s.episode(path.rsplit('/',1)[1])
                if s.config.get('canonical'):
                    target=str(Path(ep['current_data']).parent/'打开看板.html').replace('\\','/')
                    self.send_response(302);self.send_header('Location','/project/'+quote(target));self.send_header('Content-Length','0');self.end_headers();return
                if not ep['delivery_board']:raise ValueError('本集尚无交付看板。')
                self.send_response(302);self.send_header('Location','/project/'+__import__('urllib.parse',fromlist=['quote']).quote(ep['delivery_board']));self.send_header('Content-Length','0');self.end_headers();return
            if path.startswith('/project/'):
                file=under(s.root,path[len('/project/'):])
                if s.config.get('canonical'):
                    from canonical import catalog, html, public_file
                    for e in catalog(s.root,project=s.project)[0]:
                        if file == (s.root/e['current_data']).with_name('打开看板.html'):
                            return self.html(html(s.root,e['id'],project=s.project))
                    if public_file(s.root,file,project=s.project):return self.file(file)
                    raise ValueError('此文件未绑定在现行制作数据中。')
                if not any(file.is_relative_to(s.root/x) for x in ('剧集','设定库','素材库')) or file.suffix.lower() not in ('.html','.png','.jpg','.jpeg','.webp','.css','.js'):
                    raise ValueError('该文件不能通过看板访问。')
                return self.file(file)
            static={'/':'index.html','/app.js':'app.js','/editor.js':'editor.js','/style.css':'style.css',
                    '/board-editor.js':'board-editor.js','/board-editor.css':'board-editor.css'}
            if path in static:return self.file(HERE/'web'/static[path])
            return self.json({'error':'页面不存在。'},404)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        except (ValueError,KeyError,FileNotFoundError) as error:self.json({'error':str(error)},400)
        except Exception:self.json({'error':'读取失败，请稍后刷新；现有任务不会受到影响。'},500)

    def do_POST(self):
        origin=self.headers.get('Origin')
        allowed=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
        if not self.local() or origin not in allowed or not secrets.compare_digest(self.headers.get('X-Studio-Token',''),self.server.csrf):
            return self.json({'error':'来源校验失败，请从本机看板重新操作。'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2*1024*1024:raise ValueError('请求大小无效。')
            if self.headers.get_content_type()!='application/json':raise ValueError('仅接受 JSON 请求。')
            data=json.loads(self.rfile.read(length));path=urlsplit(self.path).path;s=self.server.studio
            if path=='/api/mixes':return self.json(s.save_mix(data))
            if path=='/api/annotations':return self.json(s.save_annotation(data))
            if path=='/api/export-srt':
                from exporter import build_srt
                return self.json(build_srt(s,data))
            if path=='/api/profiles':return self.json(s.save_profile(data))
            if path=='/api/profiles/delete':return self.json(s.delete_profile(data))
            if path=='/api/profiles/models':return self.json(s.fetch_models(data))
            if path=='/api/profiles/test':return self.json(s.test_profile(data))
            if path=='/api/unit-draft':
                from editing import save_draft, EditConflict
                try:return self.json(save_draft(s,data))
                except EditConflict as error:return self.json({'error':str(error),'conflict':True},409)
            if path=='/api/regenerate':return self.json(s.regenerate(data),202)
            if path=='/api/export':return self.json(self.server.exporter.start(data),202)
            return self.json({'error':'此操作不存在；主队列由 agent 管理。'},404)
        except (ValueError,KeyError,TypeError) as error:self.json({'error':str(error)},400)
        except Exception:self.json({'error':'操作未完成，请刷新核对状态后重试。'},500)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);parser.add_argument('--open',action='store_true');parser.add_argument('--project',help='Scope dashboard and queue to this drama directory');args=parser.parse_args()
    studio=Studio(studio_config(args.project) if args.project else None)
    try:server=Server(('127.0.0.1',args.port),studio)
    except OSError:
        raise SystemExit('本机端口已占用。若看板已启动，请打开 http://127.0.0.1:'+str(args.port))
    regen=Regenerator(studio);threading.Thread(target=regen.run,daemon=True).start()
    url=f'http://127.0.0.1:{args.port}'
    print('制作看板 '+url+(f' [{studio.project}]' if studio.project else ''),flush=True)
    if args.open:webbrowser.open(url)
    try:server.serve_forever()
    finally:regen.stop.set();server.server_close()


if __name__=='__main__':main()
