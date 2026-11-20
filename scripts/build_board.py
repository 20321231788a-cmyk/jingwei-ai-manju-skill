"""Render canonical production JSON with the studio palette and shot navigation.

Offline, standard-library only; never submits media or changes review state.
"""
import argparse
import html
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote

FIELDS = ('subject_definitions', 'summary', 'retention_analysis',
          'detailed_description', 'overall_soundscape', 'non_diegetic_music')
STATES = {'draft': '制作预览 · 尚未完成统一审阅',
          'reviewed': '已统一审阅 · 待用户终审',
          'user_approved': '用户已终审通过 · 视频状态见制作任务'}
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
SHOT = re.compile(r'\[Shot (\d+)\](?:\s+At (\d{2}):([0-5]\d)\.(\d{3}),)?')


def split_shots(description):
    """Keep the official shot boundaries; never infer cuts from elapsed time."""
    matches = list(SHOT.finditer(description))
    intro = description[:matches[0].start()].strip() if matches else description.strip()
    shots = []
    for i, match in enumerate(matches):
        cut = (int(match[2]) * 60 + int(match[3]) + int(match[4]) / 1000
               if match[2] is not None else None)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(description)
        shots.append(dict(number=int(match[1]), cut=cut, label=match[0],
                          body=description[match.end():end].strip()))
    return intro, shots


def validate_shots(description, duration, uid):
    errors = []
    _, shots = split_shots(description)
    if not shots:
        return [f'{uid}：H3正文缺少实际Shot标记']
    previous = 0
    for i, shot in enumerate(shots, 1):
        if shot['number'] != i or not shot['body']:
            errors.append(f'{uid}：Shot须从1连续编号并包含镜头描述')
        cut = shot['cut']
        if i == 1:
            if cut is not None:
                errors.append(f'{uid}：首镜不标时间戳')
        elif cut is None or not previous < cut < duration:
            errors.append(f'{uid}：后续Shot切点须递增且位于请求时长内')
        else:
            previous = cut
    return errors


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def text(v):
    return isinstance(v, str) and bool(v.strip())


def resolve(base, value):
    return (base / value).resolve()


def display_units(data):
    """Wan groups are an editable view; keep source H3 units and frozen jobs intact."""
    return data.get('seedance_groups', []) if data.get('active_model') == 'seedance2' else data.get('generation_groups', []) if data.get('active_model') == 'wan3' else data['units']


def model_prompt(unit):
    if unit.get('model') in ('wan3', 'seedance2'):
        return unit.get('prompt_text_en', '') if unit.get('prompt_language') == 'en' else unit.get('prompt_text', '')
    if unit.get('h3_layout') == 'two_complete_15s_blocks':
        return '\n------\n'.join('\n\n'.join(f'{f}:\n{seg.get("prompt", {}).get(f) or "待补"}' for f in FIELDS)
                                for seg in unit.get('prompt_segments', []))
    return '\n\n'.join(f'{f}:\n{unit.get("prompt", {}).get(f) or "待补"}' for f in FIELDS)


def source_revision(unit):
    import hashlib
    return hashlib.sha256(json.dumps(unit, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_text_groups(data, lookup, base, final, model, duration, collection, label):
    errors, warnings, ids = [], [], set()
    source = {u['id']: u for u in data.get('units', [])}
    groups = data.get(collection)
    if not isinstance(groups, list) or not groups:
        return [f'{label}缺少{duration}秒生成段'], []
    for g in groups:
        uid = g.get('id', '')
        if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', uid) or uid in ids or uid in source:
            errors.append(f'{uid}：{label}段ID无效或重复')
        ids.add(uid)
        if g.get('model') != model or g.get('duration_s') != duration:
            errors.append(f'{uid}：{label}生成须固定{duration}秒')
        for key in ('title', 'source_locator', 'scene', 'framing', 'action', 'camera', 'sound', 'continuity', 'directing_summary', 'prompt_text'):
            if not text(g.get(key)):
                errors.append(f'{uid}：缺少{key}')
        if not isinstance(g.get('dialogue'), list) or not all(isinstance(s, str) for s in g.get('dialogue', [])):
            errors.append(f'{uid}：对白格式无效')
        bindings = g.get('references', [])
        if not isinstance(bindings, list) or len(set(bindings)) != len(bindings):
            errors.append(f'{uid}：图片绑定无效')
            bindings = []
        elif not bindings:
            if data.get('script_only') is True and not final:
                warnings.append(f'{uid}：仅脚本审阅，图片待补；不可提交生成')
            else:
                errors.append(f'{uid}：图片绑定无效')
        for rid in bindings:
            r = lookup.get(rid)
            if not r or r.get('type') == 'video_reference':
                errors.append(f'{uid}：{label}当前仅使用已确认图片：{rid}')
            elif not r.get('path') or not resolve(base, r['path']).is_file() or r.get('verified') is not True:
                (errors if final else warnings).append(f'{uid}/{rid}：素材缺失或未核验')
        if g.get('prompt_language') == 'en' and not text(g.get('prompt_text_en')):
            errors.append(f'{uid}：英文{label}正文待同步')
        prompt = '\n'.join(value for value in (g.get('prompt_text'), g.get('prompt_text_en')) if isinstance(value, str))
        for n in re.findall(r'(?:图|@图片)\s*(\d+)', prompt):
            if not 1 <= int(n) <= len(bindings):
                errors.append(f'{uid}：图{n}无对应绑定')
        if re.search(r'<(?:Picture|Subject|Video)\s+\d+>|\[Shot\s', prompt):
            errors.append(f'{uid}：{label}正文残留H3标签')
        previous = 0
        shots = g.get('shots', [])
        for i, shot in enumerate(shots, 1):
            start, end = shot.get('start_s'), shot.get('end_s')
            if (not number(start) or not number(end) or start != previous or not start < end <= duration
                    or shot.get('number') != i or not text(shot.get('description'))):
                errors.append(f'{uid}：分镜时间须连续覆盖0—{duration}秒')
                break
            previous = end
        if not shots or previous != duration:
            errors.append(f'{uid}：分镜未覆盖完整{duration}秒')
        for sid in g.get('source_units', []):
            if sid not in source or g.get('source_revisions', {}).get(sid) != source_revision(source[sid]):
                errors.append(f'{uid}：来源{sid}已改变，须同步{label}正文')
        for event in g.get('dialogue_events', []):
            start, end = event.get('start_s'), event.get('end_s')
            if not (number(start) and number(end) and 0 <= start < end <= duration and text(event.get('line')) and text(event.get('performance'))):
                errors.append(f'{uid}：对白时段或表演描述无效')
    return errors, warnings


def validate_wan_groups(data, lookup, base, final):
    return validate_text_groups(data, lookup, base, final, 'wan3', 30, 'generation_groups', 'Wan3')


def validate_source_dialogue(data, base):
    """Compare the saved quote map with the actual source, not with itself.

    By default, episodes with thrill_plan or strict_verbatim=False allow
    short-drama dialogue condensation and punchline sharpening while keeping
    dialogue_events synced with the active model prompt.
    """
    manifest = data.get('source_quote_manifest')
    classification = data.get('source_quote_classification')
    if not isinstance(manifest, dict) or not isinstance(classification, dict):
        # Older approved episodes use their own split/narration identifiers.
        return []
    errors = []
    collected = {}
    for group in display_units(data):
        for event in group.get('dialogue_events', []):
            if 'source_quote' not in event:
                continue
            key = str(event['source_quote'])
            line = event.get('line', '')
            collected[key] = collected.get(key, '') + line
            if event.get('text', line) != line or line not in model_prompt(group):
                errors.append(f"{group.get('id')}：来源引号段{key}与生效模型正文不同步")
    strict = data.get('strict_verbatim')
    if strict is False or (strict is None and 'thrill_plan' in data):
        return errors
    source = resolve(base, data.get('source', ''))
    if not source.is_file():
        return errors  # The ordinary source check reports this separately.
    raw = source.read_text(encoding='utf-8-sig')
    quotes = re.findall('“(.*?)”', raw, re.S)
    expected = {str(i): value for i, value in enumerate(quotes, 1)}
    if manifest != expected:
        errors.append('原件引号段已变化，须按实际原文同步对白清单及分镜')
    spoken = {str(i) for i in classification.get('spoken', [])}
    nonspoken = {str(i) for i in classification.get('nonspoken', [])}
    numeric = {key for key in spoken | nonspoken if key.isdecimal()}
    if spoken & nonspoken or numeric != set(expected):
        errors.append('原件引号段须完整区分对白与非发声文字')
    if set(collected) != spoken:
        errors.append('实际发声对白与原件对白分类不一致')
    for key, line in collected.items():
        if (key.isdecimal() and line != expected.get(key)) or (not key.isdecimal() and line not in raw):
            errors.append(f'原件引号段{key}：对白缺失、重复或分句改字')
    return errors


WEAK_MICRO_RE = re.compile(r'眼神微|嘴角微|眉头微|手指轻|轻轻攥|微微一怔|轻轻点头')
STRONG_ACTION_RE = re.compile(r'拍桌|拍案|猛拍|震飞|震翻|震退|指鼻|指着|怒指|扣腕|扣住|拎领|拎起|逼视|逼退|逼近|摔碎|撕毁|炸裂|骤亮|掀翻|甩袖|踏前|踹|硬切|骤切|急推|上摇|仰拍|俯拍|极特写')
FIRST_SHOT_RE = re.compile(r'(?:^|\n)\s*(?:0(?:\.0+)?\s*[–—~-]\s*\d|分镜\s*1|\[Shot\s*1\])')
SPOKEN_CHAR_RE = re.compile(r'[\u4e00-\u9fffA-Za-z0-9]')


def validate_thrill_and_anti_bland(data, *, highlight_units=None):
    """Enforce thrill drama structure slots and multi-model anti-bland gates."""
    errors, warnings = [], []
    has_thrill = 'thrill_plan' in data or data.get('enforce_thrill') is True
    plan = data.get('thrill_plan')
    units = display_units(data)
    if has_thrill:
        if not isinstance(plan, dict):
            errors.append('thrill_plan 必须为爽剧爆点骨架对象')
            plan = {}
        for k in ('opening_hook_3s', 'core_pain_point', 'payoff_climax', 'slice_highlight', 'ending_hook'):
            if not text(plan.get(k)):
                errors.append(f'thrill_plan 缺少必填爆点槽位：{k}')
        level = plan.get('thrill_level')
        if level is not None and (not number(level) or not 1 <= level <= 10):
            errors.append('thrill_plan.thrill_level 须为1–10之间的爽点强度数值')
        highlight = str(plan.get('slice_highlight', ''))
        golden_lines = [q.strip() for q in re.findall(r'“([^”]+)”|"([^"]+)"', highlight) for q in q if q.strip()]
        if text(plan.get('golden_line')):
            golden_lines.append(plan['golden_line'].strip())
        episode_units = units if highlight_units is None else highlight_units
        if golden_lines and episode_units:
            all_prompts = '\n'.join(
                model_prompt(u) + '\n' + str(u.get('prompt_zh', {}).get('detailed_description', '')) + '\n' + '\n'.join(u.get('dialogue', []))
                for u in episode_units
            )
            for gline in golden_lines:
                if len(SPOKEN_CHAR_RE.findall(gline)) > 16:
                    warnings.append(f'切片金句建议压缩至12字以内（当前较长）：{gline}')
                if gline not in all_prompts:
                    errors.append(f'跨模型爆点丢失：thrill_plan切片金句“{gline}”未在当前模型正文中落地')
    for u in units:
        uid = u.get('id', '')
        if has_thrill or 'dramatic_arc' in u:
            arc = u.get('dramatic_arc', '')
            if not text(arc) or not any(sep in arc for sep in ('→', '->', '—', '/', '；')):
                errors.append(f'{uid}：缺少dramatic_arc三拍爆点弧线（需用“→”标出施压→加码→反杀/断钩转折）')
        model = u.get('model') or data.get('active_model') or 'h3'
        if has_thrill and model in ('wan3', 'seedance2'):
            ptext = u.get('prompt_text', '')
            if text(ptext):
                m = FIRST_SHOT_RE.search(ptext)
                if m:
                    header = ptext[:m.start()].strip()
                    limit = 95 if model == 'seedance2' else 110
                    if len(header) > limit:
                        errors.append(f'{uid}：{model}提示词头部超过{limit}字（当前{len(header)}字），须删减静态材质套话以保留动作权重')
            events = u.get('dialogue_events', [])
            if events:
                total_chars = sum(len(SPOKEN_CHAR_RE.findall(e.get('line', ''))) for e in events)
                max_chars = 38 if model == 'seedance2' else 85
                if total_chars > max_chars:
                    errors.append(f'{uid}：{u.get("duration_s", "")}秒段台词总字数超标（{total_chars}字>{max_chars}字），须脱水提纯留出动作呼吸区')
        if has_thrill:
            check_texts = [u.get('action', '')] + [s.get('description', '') for s in u.get('shots', []) if isinstance(s, dict)]
            for t in check_texts:
                if text(t) and WEAK_MICRO_RE.search(t) and not STRONG_ACTION_RE.search(t):
                    errors.append(f'{uid}：存在微表情站桩描述，须外化为高幅度动作与大反差景别')
                    break
    return errors, warnings


def validate(data, base, final=False, *, highlight_units=None):
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ['制作数据必须为JSON对象'], []
    for k in ('project', 'episode', 'title', 'source', 'aspect_ratio', 'style', 'director_style'):
        if not text(data.get(k)):
            errors.append(f'缺少 {k}')
    if data.get('review_status') not in STATES:
        errors.append('review_status 无效')
    if final and data.get('review_status') not in ('reviewed', 'user_approved'):
        errors.append('尚未完成统一审阅，不能导出终审包')
    if final and data.get('script_only') is True:
        errors.append('当前仅完成脚本审阅，素材待补，不能提交生成')
    errors.extend(validate_source_dialogue(data, base))
    for key in ('additional_sources', 'pending_items'):
        if not isinstance(data.get(key, []), list) or not all(isinstance(s, str) for s in data.get(key, [])):
            errors.append(f'{key} 必须为字符串列表')
    sources = [data.get('source', '')] + (data.get('additional_sources', []) if isinstance(data.get('additional_sources', []), list) else [])
    for source in sources:
        if not text(source) or not resolve(base, source).is_file():
            (errors if final else warnings).append(f'原件不存在：{source}')
    refs = data.get('references', [])
    if not isinstance(refs, list):
        errors.append('references 必须为列表')
        refs = []
    lookup = {}
    for ref in refs:
        if not isinstance(ref, dict) or not text(ref.get('id')):
            errors.append('素材缺少id')
            continue
        rid = ref['id']
        if rid in lookup:
            errors.append(f'重复素材id：{rid}')
        lookup[rid] = ref
        if ref.get('type') not in ('character_sheet', 'prop', 'background', 'video_reference'):
            errors.append(f'{rid}：不允许的参考素材类型')
        if not text(ref.get('purpose')):
            errors.append(f'{rid}：缺少用途')
        path = ref.get('path')
        suffixes = ('.mp4',) if ref.get('type') == 'video_reference' else ('.png', '.jpg', '.jpeg', '.webp')
        if path and (not isinstance(path, str) or Path(path).suffix.lower() not in suffixes):
            errors.append(f'{rid}：参考素材格式与用途不符')
    units = data.get('units')
    if not isinstance(units, list) or (not units and data.get('active_model') not in ('wan3', 'seedance2')):
        return errors + ['缺少分镜单元'], warnings
    ids = set()
    for unit in units:
        if not isinstance(unit, dict):
            errors.append('单元必须为对象')
            continue
        uid = unit.get('id', '')
        if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', uid) or uid in ids:
            errors.append(f'无效或重复单元id：{uid}')
        ids.add(str(uid))
        for k in ('title', 'source_locator', 'scene', 'framing', 'action', 'camera', 'sound', 'continuity'):
            if not text(unit.get(k)):
                errors.append(f'{uid}：缺少 {k}')
        if 'directing_summary' in unit and not text(unit['directing_summary']):
            errors.append(f'{uid}：directing_summary须为非空拍法概述')
        duration = unit.get('duration_s')
        if unit.get('h3_layout') == 'two_complete_15s_blocks':
            # A provider packet contains two independently validated H3 targets;
            # the official single-target 4–15-second limit below stays intact.
            segments = unit.get('prompt_segments', [])
            if duration != 30 or not isinstance(segments, list) or len(segments) != 2:
                errors.append(f'{uid}：H3组合包须为两个完整15秒子段，共30秒')
                continue
            children = []
            for i, seg in enumerate(segments, 1):
                if seg.get('part') != i or seg.get('duration_s') != 15 or tuple(seg.get('prompt', {})) != FIELDS:
                    errors.append(f'{uid}/P{i}：H3子段须按序包含15秒及官方六字段')
                    continue
                children.append({**unit, 'id': uid + f'_P{i}', 'duration_s': 15,
                                 'prompt': seg['prompt'], 'prompt_zh': seg.get('prompt_zh', {}),
                                 'h3_layout': 'single_target'})
            nested = {**data, 'units': children}
            nested_errors, nested_warnings = validate(nested, base, final)
            errors.extend(nested_errors); warnings.extend(nested_warnings)
            if unit.get('compiled_h3_prompt') != model_prompt(unit):
                errors.append(f'{uid}：组合正文与两个现行子段不一致')
            continue
        if not number(duration) or not 4 <= duration <= 15 or int(duration) != duration:
            errors.append(f'{uid}：请求时长须为4–15整数秒')
            continue
        generation = unit.get('generation', {})
        if not isinstance(generation, dict):
            errors.append(f'{uid}：generation须为生成档位对象')
            generation = {}
        if generation:
            if generation.get('protocol') not in ('rb-v1', 'sparkcine-v1'):
                errors.append(f'{uid}：生成档位须明确接口协议')
            if generation.get('preset') not in ('reference', 'easy_15'):
                errors.append(f'{uid}：该生成档位尚未支持')
            for k in ('width', 'height'):
                if not number(generation.get(k)) or generation[k] <= 0 or int(generation[k]) != generation[k]:
                    errors.append(f'{uid}：生成画幅须为正整数')
            interval = generation.get('adopted_interval')
            narrative = generation.get('narrative_seconds')
            if (not isinstance(interval, list) or len(interval) != 2 or not all(number(v) for v in interval)
                    or not 0 <= interval[0] < interval[1] <= duration):
                errors.append(f'{uid}：剪辑采用区间须位于请求时长内')
            elif not number(narrative) or abs(narrative - (interval[1] - interval[0])) > 1e-6:
                errors.append(f'{uid}：剧情时长须与剪辑采用区间一致')
        kind = unit.get('kind')
        if kind not in ('long', 'short'):
            errors.append(f'{uid}：kind须为long或short')
        elif not ((kind == 'long' and 12 <= duration <= 15) or (kind == 'short' and 4 <= duration <= 6)) and not text(unit.get('duration_reason')):
            errors.append(f'{uid}：偏离长短单元时长需明确依据')
        dialogue = unit.get('dialogue', [])
        if not isinstance(dialogue, list) or not all(isinstance(s, str) for s in dialogue):
            errors.append(f'{uid}：dialogue须为完整对白字符串列表')
        bindings = unit.get('references', [])
        if not isinstance(bindings, list) or not all(isinstance(r, str) for r in bindings):
            errors.append(f'{uid}：references须为素材id列表')
            bindings = []
        if len(bindings) != len(set(bindings)):
            errors.append(f'{uid}：重复绑定素材')
        if not bindings:
            (errors if final else warnings).append(f'{uid}：全能参考素材尚未绑定')
        if 'mute_reference_video' in unit and not isinstance(unit['mute_reference_video'], bool):
            errors.append(f'{uid}：mute_reference_video须为布尔值')
        for rid in bindings:
            ref = lookup.get(rid)
            if ref is None:
                errors.append(f'{uid}：未知素材 {rid}')
            elif not text(ref.get('path')) or not resolve(base, ref['path']).is_file() or ref.get('verified') is not True:
                (errors if final else warnings).append(f'{uid}/{rid}：素材缺失或尚未实际核验')
        prompt = unit.get('prompt', {})
        if not isinstance(prompt, dict):
            errors.append(f'{uid}：prompt须为六段字段对象')
            prompt = {}
        for field in FIELDS:
            if not text(prompt.get(field)):
                (errors if final else warnings).append(f'{uid}：H3字段待补 {field}')
        detail = prompt.get('detailed_description', '')
        if text(detail):
            errors.extend(validate_shots(detail, duration, uid))
        translated = unit.get('prompt_zh', {})
        if not isinstance(translated, dict):
            errors.append(f'{uid}：prompt_zh须为中文显示字段对象')
            translated = {}
        chinese = translated.get('detailed_description', '')
        if not text(chinese):
            (errors if final else warnings).append(f'{uid}：H3镜头中文译文待补')
        elif text(detail):
            original_shots = split_shots(detail)[1]
            translated_shots = split_shots(chinese)[1]
            if [(s['number'], s['cut']) for s in original_shots] != [(s['number'], s['cut']) for s in translated_shots]:
                errors.append(f'{uid}：中文镜头与H3正文的Shot编号或切点不一致')
            if not translated_shots or any(not s['body'] for s in translated_shots):
                errors.append(f'{uid}：中文镜头缺少完整描述')
            if re.findall(r'<d>(.*?)</d>', detail, re.S) != re.findall(r'<d>(.*?)</d>', chinese, re.S):
                errors.append(f'{uid}：中文镜头译文改变了原对白或歌词')
        video_count = sum(lookup.get(r, {}).get('type') == 'video_reference' for r in bindings)
        for label, count in (('Picture', len(bindings)-video_count), ('Video', video_count)):
            for n in re.findall(r'<'+label+r'\s+(\d+)>', '\n'.join(str(v) for v in prompt.values())):
                if not 1 <= int(n) <= count:
                    errors.append(f'{uid}：{label} {n} 无对应绑定')
    if data.get('active_model') == 'wan3':
        wan_errors, wan_warnings = validate_wan_groups(data, lookup, base, final)
        errors.extend(wan_errors)
        warnings.extend(wan_warnings)
    if data.get('active_model') == 'seedance2':
        seed_errors, seed_warnings = validate_text_groups(data, lookup, base, final, 'seedance2', 15, 'seedance_groups', 'Seedance 2.0')
        errors.extend(seed_errors); warnings.extend(seed_warnings)
    thrill_errors, thrill_warnings = validate_thrill_and_anti_bland(data, highlight_units=highlight_units)
    errors.extend(thrill_errors); warnings.extend(thrill_warnings)
    return errors, list(dict.fromkeys(warnings))


def esc(value):
    return html.escape(str(value), quote=True)


def paragraph(label, value):
    return f'<p><strong>{esc(label)}</strong>　{esc(value).replace(chr(10), "<br>")}</p>'


def render_chinese_shots(unit):
    if unit.get('model') in ('wan3', 'seedance2'):
        return '<section class="chinese-shots"><h3>' + ('Seedance 2.0' if unit.get('model') == 'seedance2' else 'Wan3') + '分镜（中文）</h3><p>' + esc(unit.get('prompt_text', '')).replace('\n', '<br>') + '</p></section>'
    description = unit.get('prompt_zh', {}).get('detailed_description', '')
    parts = ['<section class="chinese-shots"><h3>H3镜头（中文）</h3>']
    if not text(description):
        parts.append('<p class="muted">中文镜头译文待补。</p>')
    else:
        intro, shots = split_shots(description)
        if intro:
            parts.append(paragraph('画面风格', intro))
        for shot in shots:
            parts.append(f'<h4>{esc(shot["label"].rstrip(","))}</h4><p>{esc(shot["body"]).replace(chr(10), "<br>")}</p>')
    parts.append('</section>')
    return '\n'.join(parts)


def url(base, value, output):
    target = resolve(base, value)
    try:
        return quote(Path(os.path.relpath(target, output.parent)).as_posix(), safe='/')
    except ValueError:
        return target.as_uri()


def render(data, base, output, warnings):
    template = (ASSETS / 'episode-board.html').read_text(encoding='utf-8-sig')
    css = re.search(r'<style>(.*?)</style>', template, re.S).group(1)
    js = re.search(r'<script>(.*?)</script>', template, re.S).group(1)
    refs = {r['id']: r for r in data['references']}
    units = display_units(data)
    wan = data.get('active_model') in ('wan3', 'seedance2')
    seedance = data.get('active_model') == 'seedance2'
    total = sum(u['duration_s'] for u in units)
    state = STATES[data['review_status']]
    used = {r for u in units for r in u.get('references', [])}
    present = [r for r in used if text(refs[r].get('path')) and resolve(base, refs[r]['path']).is_file()]
    video_count = sum(refs[r].get('type') == 'video_reference' for r in present)
    summary = f'{len(units)}个生成单元 · 请求时长合计{total:g}秒（非最终剪辑时长） · {len(present)-video_count}张实际绑定图片'
    if video_count:
        summary += f' · {video_count}段动作/运镜参考视频'
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             f'<title>{esc(data["title"])}</title><style>{css}</style></head><body><main>',
             f'<header><small>{esc(data["project"])} · {esc(data["episode"])}</small><h1>{esc(data["title"])}<br>当前图文分镜</h1><p>{esc(summary)}</p>']
    style_raw = data.get('style', '')
    style_tag = data.get('style_name') or ('r2混合媒介' if ('r2' in style_raw or '混合媒介' in style_raw) else '自定义画风')
    for tag in (data['aspect_ratio'], style_tag, 'Seedance 2.0 · 图片参考 · 每段15秒' if seedance else 'Wan3 · 图片参考 · 每段30秒' if wan else 'MiniMax-H3 · 全能多模态参考' if video_count else 'MiniMax-H3 · 全能图片参考'):
        parts.append(f'<span class="tag">{esc(tag)}</span>')
    parts.append('<nav>')
    for i, source in enumerate([data['source']] + data.get('additional_sources', []), 1):
        if resolve(base, source).is_file():
            parts.append(f'<a href="{esc(url(base, source, output))}">原件{i}</a>')
    parts.append('</nav></header><div class="note">')
    style_display = f'[{data["style_name"]}] {style_raw}' if text(data.get('style_name')) else style_raw
    parts.extend([paragraph('状态', state + '；本页为脚本审核，实际视频状态与动态验收见制作工作台。'), paragraph('画风', style_display), paragraph('导演选择', data['director_style'])])
    plan = data.get('thrill_plan')
    if isinstance(plan, dict) and any(text(plan.get(k)) for k in ('opening_hook_3s', 'core_pain_point', 'payoff_climax', 'slice_highlight', 'ending_hook')):
        level_tag = f'（爽点强度 {plan["thrill_level"]}/10）' if number(plan.get('thrill_level')) else ''
        for label, key in (('前3秒痛点钩', 'opening_hook_3s'), ('核心受压痛点', 'core_pain_point')):
            if text(plan.get(key)):
                parts.append(paragraph(label, plan[key]))
        if text(plan.get('payoff_climax')):
            parts.append(paragraph('宣泄爆点' + level_tag, plan['payoff_climax']))
        for label, key in (('切片名场面与金句', 'slice_highlight'), ('集尾断钩', 'ending_hook')):
            if text(plan.get(key)):
                parts.append(paragraph(label, plan[key]))
    if wan:
        configured = any((u.get('generation', {}).get('protocol') in ('doubao-canvas-v1', 'scenora-v1')) if seedance else (u.get('generation', {}).get('protocol') in ('wan-portal-v1', 'scenora-v1')) for u in units)
        parts.append(paragraph('生成状态', 'Seedance 2.0中文15秒稿，按本次授权经单一豆包会话生成；任务查询下载见制作工作台。' if seedance and configured else 'Wan3分镜与提示词可在工作台原位编辑；已接入万万工作台，任务状态见工作台。' if configured else '当前模型尚未配置提交接口，提交禁用。'))
        parts.append('<details><summary>原分镜与独立片头对照（原ID及H3正文保留在制作数据中）</summary>' + ''.join(paragraph(u['id'], f'{u["title"]} · 原{u["duration_s"]}秒') for u in data['units']) + '</details>')
    for item in data.get('pending_items', []):
        parts.append(paragraph('待用户决定', item))
    for warning in warnings:
        parts.append(paragraph('待完成', warning))
    parts.append('</div><nav>' + ''.join(f'<a href="#{u["id"]}">{u["id"]}</a>' for u in units) + '</nav>')
    for u in units:
        uid = u['id']
        parts.append(f'<article id="{uid}"><small>{uid} · {u["duration_s"]:g}秒 · {esc(u["framing"])}</small><h2>{esc(u["title"])}</h2>')
        if text(u.get('dramatic_arc')):
            parts.append(paragraph('三拍爆点弧线', u['dramatic_arc']))
        if text(u.get('slice_highlight')):
            parts.append(paragraph('切片高光与金句', u['slice_highlight']))
        if text(u.get('directing_summary')):
            parts.append(paragraph('拍法概述', u['directing_summary']))
        parts.append('<div class="frames">')
        media_counts = {'Picture': 0, 'Video': 0}
        for rid in u.get('references', []):
            ref = refs[rid]
            label = 'Video' if ref.get('type') == 'video_reference' else 'Picture'
            media_counts[label] += 1
            caption = f'{"图" if wan and label == "Picture" else label} {media_counts[label]} · {rid} · {ref["purpose"]}'
            if text(ref.get('path')) and resolve(base, ref['path']).is_file():
                href = esc(url(base, ref['path'], output))
                media = f'<video controls preload="metadata" style="width:100%" src="{href}"></video>' if label == 'Video' else f'<a href="{href}" target="_blank" rel="noopener"><img loading="lazy" src="{href}" alt="{esc(caption)}"></a>'
                parts.append(f'<figure>{media}<figcaption>{esc(caption)} · {"已核验" if ref.get("verified") is True else "待核验"}</figcaption></figure>')
            else:
                parts.append(f'<figure><figcaption>{esc(caption)} · 待补素材</figcaption></figure>')
        parts.append('</div>')
        if u.get('generation'):
            g = u['generation']
            a = g['adopted_interval']
            parts.append(paragraph('生成与剪辑', f'{g["protocol"]} · {g["preset"]} · {g["width"]}×{g["height"]}；请求{u["duration_s"]:g}秒，原剧情{g["narrative_seconds"]:g}秒，计划采用{a[0]:g}–{a[1]:g}秒；实际裁点须播放核验。'))
        for label, key in (('原件定位','source_locator'), ('场景','scene'), ('画面与表演','action'), ('摄影','camera')):
            parts.append(paragraph(label, u[key]))
        parts.append(render_chinese_shots(u))
        parts.extend(f'<blockquote>{esc(d)}</blockquote>' for d in u.get('dialogue', []))
        parts.extend([paragraph('声音', u['sound']), paragraph('接点', u['continuity']), paragraph('参考图输入设计', ' → '.join(u.get('references', [])) or '待绑定')])
        prompt = model_prompt(u)
        parts.append(f'<details id="unit-{uid}"><summary>{uid} · {u["duration_s"]:g}秒 · 完整{"Seedance 2.0" if seedance else "Wan3英文" if wan and u.get("prompt_language") == "en" else "Wan3" if wan else "H3"}提示词草稿</summary><button type="button" onclick="copyPrompt(this)">复制完整提示词</button><pre>{esc(prompt)}</pre>{paragraph("后期说明", u.get("post", "无额外后期说明"))}</details></article>')
    parts.append(f'<footer class="muted">{esc(summary)} · {esc(state)}</footer></main><script>{js}</script></body></html>')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--final-review', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve()
    output = (args.output or source.with_name('打开看板.html')).resolve()
    if output == source or output.suffix.lower() != '.html':
        parser.error('输出必须为独立HTML文件')
    try:
        data = json.loads(source.read_text(encoding='utf-8-sig'))
        errors, warnings = validate(data, source.parent, args.final_review)
        for error in errors:
            print('ERROR: ' + error)
        for warning in warnings:
            print('WARN: ' + warning)
        if errors:
            return 1
        if args.check:
            print('结构检查通过；不代表语义或成片验收通过。')
            return 0
        content = render(data, source.parent, output, warnings)
        if not output.exists() or output.read_text(encoding='utf-8') != content:
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_suffix('.html.tmp')
            temp.write_text(content, encoding='utf-8')
            temp.replace(output)
        print(output)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('ERROR: ' + str(exc))
        return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
