"""Chinese unit drafts live beside the canonical prompt, never inside frozen jobs."""
import copy
import hashlib
import json
import re

from model import load_json, save_json, stamp, under

FIELDS = ('title', 'scene', 'duration_s', 'action', 'dialogue', 'camera', 'framing', 'chinese_description',
          'sound', 'continuity', 'directing_summary')


class EditConflict(ValueError):
    pass


def unit_revision(unit):
    return hashlib.sha256(json.dumps(unit, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def readable_action(unit):
    text = unit.get('action') or unit.get('prompt_zh', {}).get('detailed_description', '')
    names = {'Lin Hao': '林昊', 'Su Qi': '苏祈', 'Chu Weiwei': '楚薇薇',
             'the Qin family heir': '秦少'}
    labels = {}
    for match in re.finditer(r'<Subject (\d+)> is ([^\n]+)', unit.get('prompt', {}).get('subject_definitions', '')):
        description = match[2]
        name = next((zh for en, zh in names.items() if en in description), None)
        if not name:
            low = description.lower()
            name = ('当票' if 'ticket' in low else '铜钱' if 'coin' in low else
                    '车辆' if 'sedan' in low or 'vehicle' in low else
                    '场景' if any(s in low for s in ('hall', 'environment', 'courtyard', 'lane', 'room')) else None)
        if name:
            labels[match[1]] = name
    text = re.sub(r'<Subject (\d+)>', lambda m: labels.get(m[1], '参考对象'+m[1]), text)
    text = re.sub(r'<Picture (\d+)>', r'参考图\1', text)
    text = re.sub(r'<d>\[Chinese\]\s*(.*?)</d>', r'“\1”', text, flags=re.S)
    text = re.sub(r'\[Shot (\d+)\] At ([0-9:.]+),', r'镜头\1（\2切镜）：', text)
    text = re.sub(r'\[Shot (\d+)\]', r'镜头\1：', text)
    text = re.sub(r'\s*\(S\d+(?:,S\d+)*\)', '', text)
    return text.replace('<scenetrans>', '（对白跨切连续）').strip()


def committed_values(unit):
    return {field: ((unit.get('prompt_text', '') if unit.get('model') in ('wan3', 'seedance2') else unit.get('prompt_zh', {}).get('detailed_description', '')) if field == 'chinese_description' else
                    readable_action(unit) if field == 'action' else
                    copy.deepcopy(unit.get(field, [] if field == 'dialogue' else 12 if field == 'duration_s' else '')))
            for field in FIELDS}


def pending(unit):
    return bool(unit.get('editor_draft', {}).get('state') == 'pending_sync')


def public_unit(unit, eid):
    return {**unit, 'id': eid+'_'+unit['id'], 'local_id': unit['id'],
            'edit_revision': unit_revision(unit),
            'editable_values': {**committed_values(unit), **copy.deepcopy(unit['editor_draft']['values'])} if pending(unit) else committed_values(unit),
            'pending_sync': pending(unit)}


def save_draft(studio, data):
    if not studio.config.get('canonical'):
        raise ValueError('此历史剧集只支持查看，请先建立现行制作数据。')
    from canonical import catalog, digest
    eid, uid = str(data.get('episode_id', '')), str(data.get('unit_id', ''))
    with studio.lock:
        entry = next((e for e in catalog(studio.root, project=getattr(studio, 'project', None))[0] if e['id'] == eid), None)
        if entry is None:
            raise ValueError('未找到当前剧集。')
        path = under(studio.root, entry['current_data'])
        current = load_json(path)
        local_id = uid.removeprefix(eid+'_')
        from canonical import board
        unit = next((u for u in board.display_units(current) if u['id'] == local_id), None)
        if unit is None:
            raise ValueError('未找到当前镜头。')
        if data.get('base_revision') != unit_revision(unit):
            raise EditConflict('此镜头已在其他地方修改。你的输入仍保留，请先重新载入最新内容再保存。')
        if data.get('discard') is True:
            unit.pop('editor_draft', None)
        else:
            changes = data.get('changes')
            if not isinstance(changes, dict) or not changes or set(changes)-set(FIELDS):
                raise ValueError('只可编辑中文分镜、对白、运镜和时长等显示字段。')
            values = copy.deepcopy(unit['editor_draft']['values']) if pending(unit) else committed_values(unit)
            for key, value in changes.items():
                if key == 'duration_s':
                    if unit.get('model') in ('wan3', 'seedance2'):
                        expected = 15 if unit.get('model') == 'seedance2' else 30
                        if isinstance(value, bool) or value != expected:
                            raise ValueError(f'当前模型请求时长固定为{expected}秒，请在段内调整各镜时长。')
                    elif isinstance(value, bool) or not isinstance(value, int) or not 4 <= value <= 15:
                        raise ValueError('时长须为4至15秒的整数。')
                elif key == 'dialogue':
                    if not isinstance(value, list) or len(value)>200 or any(not isinstance(s,str) or len(s)>5000 for s in value):
                        raise ValueError('对白须按行保存，每行不超过5000字。')
                elif not isinstance(value, str) or len(value)>(300 if key=='title' else 100000):
                    raise ValueError('文字内容过长或格式不正确。')
                if key == 'title' and not value.strip():
                    raise ValueError('请填写镜头标题。')
                values[key] = value
            if values == committed_values(unit):
                unit.pop('editor_draft', None)
            elif not pending(unit) or values != unit['editor_draft']['values']:
                unit['editor_draft'] = {'state':'pending_sync', 'values':values, 'updated_at':stamp(),
                                        'base_prompt_sha256':hashlib.sha256((unit.get('prompt_text', '') if unit.get('model') in ('wan3', 'seedance2') else json.dumps(unit.get('prompt',{}),sort_keys=True)).encode()).hexdigest()}
        save_json(path, current)
        studio.invalidate()
        return {'unit':public_unit(unit,eid), 'episode_revision':digest(path),
                'message':('中文已保存，等待同步当前模型中文正文与段内切点。' if unit.get('model') in ('wan3', 'seedance2') else '中文已保存，等待同步英文提示词。') if pending(unit) else '已恢复当前已同步版本。'}
