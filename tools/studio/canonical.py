"""Bridge canonical storyboard JSON to the supplied studio, without a second plan file."""
import hashlib
import importlib.util
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / '.agents/skills/h3-storyboard-director'
spec = importlib.util.spec_from_file_location('storyboard_export', SKILL/'scripts/build_board.py')
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)

_SKIP_DIRS = frozenset({'tools', '制作资料', '设定库', '生成视频', '配音', '__pycache__', 'node_modules'})
_CACHE_LOCK = threading.RLock()
_EPISODE_CACHE = {}  # (root_str, path_str) -> cached episode record
_PUBLIC_INDEX = {}   # root_str -> (files_sig, public_paths_frozenset)


def _stat_sig(path):
    try:
        st = path.stat()
        return (True, st.st_mtime_ns, st.st_size)
    except OSError:
        return (False, 0, 0)


def digest(path):
    stat = path.stat()
    return cached_digest(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=2048)
def cached_digest(path, mtime, size):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _board_files(root, project=None):
    root_path = Path(root).resolve()
    scan_root = (root_path / project).resolve() if project else root_path
    if not scan_root.is_relative_to(root_path) or not scan_root.is_dir():
        return []
    found = []

    def walk(directory):
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError:
            return
        board_entry = next((e for e in entries if e.name == '制作数据.json' and e.is_file(follow_symlinks=False)), None)
        if board_entry is not None:
            found.append(Path(board_entry.path))
            return
        for entry in entries:
            name = entry.name
            if name.startswith('.'):
                continue
            if entry.is_dir(follow_symlinks=False):
                if name in _SKIP_DIRS:
                    continue
                walk(entry.path)

    walk(scan_root)
    found.sort()
    return found


def discover_projects(root):
    root_path = Path(root).resolve()
    projects = []
    try:
        top_dirs = sorted(
            [p for p in root_path.iterdir() if p.is_dir() and not p.name.startswith('.') and p.name not in _SKIP_DIRS and p.name != 'output'],
            key=lambda p: p.name,
        )
    except OSError:
        return []
    for d in top_dirs:
        files = _board_files(root_path, project=d.name)
        if files:
            projects.append({'name': d.name, 'episodes': len(files)})
    return projects


def _episode_id(relative):
    return 'P' + hashlib.sha256(relative.as_posix().encode()).hexdigest()[:10]


def _entry_unchanged(cached, json_sig):
    if cached is None or cached['json_sig'] != json_sig:
        return False
    for wpath, wsig in cached['watch_sigs']:
        if _stat_sig(wpath) != wsig:
            return False
    return True


def _load_episode(root, path):
    root_key = str(Path(root).resolve())
    path_resolved = path.resolve()
    path_key = str(path_resolved)
    json_sig = _stat_sig(path_resolved)
    with _CACHE_LOCK:
        cached = _EPISODE_CACHE.get((root_key, path_key))
        if _entry_unchanged(cached, json_sig):
            return cached

    relative = path.relative_to(root)
    watch_paths = []
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        errors, warnings = board.validate(data, path.parent)
        sources = [data.get('source', '')] + (data.get('additional_sources', []) if isinstance(data.get('additional_sources'), list) else [])
        for s in sources:
            if isinstance(s, str) and s.strip():
                watch_paths.append(board.resolve(path.parent, s))
        for r in (data.get('references') or []):
            if isinstance(r, dict) and r.get('path'):
                watch_paths.append(board.resolve(path.parent, r['path']))
        # Deduplicate while preserving order.
        unique_watch = list(dict.fromkeys(watch_paths))
        watch_sigs = [(wp, _stat_sig(wp)) for wp in unique_watch]
        if errors:
            rec = {
                'json_sig': json_sig, 'watch_sigs': watch_sigs, 'ok': False,
                'issue': f'{relative}: ' + '；'.join(errors[:3]),
                'entry': None, 'public_paths': set(), 'requests': {}, 'released': {},
            }
        else:
            key = _episode_id(relative)
            rev = cached_digest(path_resolved, json_sig[1], json_sig[2]) if json_sig[0] else digest(path)
            entry = {
                'id': key,
                'title': f'{data["project"]} · {data["episode"]} · {data["title"]}',
                'shot_count': len(board.display_units(data)),
                'current_data': relative.as_posix(),
                'delivery_board': '/board/' + key,
                'data': data,
                'review_status': data['review_status'],
                'warnings': warnings,
                'revision': rev,
            }
            root_resolved = Path(root).resolve()
            pub = {wp for wp in unique_watch if wp.is_relative_to(root_resolved)}
            rec = {
                'json_sig': json_sig, 'watch_sigs': watch_sigs, 'ok': True,
                'issue': None, 'entry': entry, 'public_paths': pub,
                'requests': {}, 'released': {}, 'source_path': path, 'relative': relative,
            }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        rec = {
            'json_sig': json_sig, 'watch_sigs': [], 'ok': False,
            'issue': f'{relative}: {exc}',
            'entry': None, 'public_paths': set(), 'requests': {}, 'released': {},
        }

    with _CACHE_LOCK:
        _EPISODE_CACHE[(root_key, path_key)] = rec
    return rec


def _build_episode_requests(root, rec, model=None):
    if not rec['ok']:
        return [], []
    if model in rec['requests']:
        return rec['requests'][model], rec['released'][model]

    entry = rec['entry']
    data = entry['data']
    source = rec['source_path']
    source_hash = entry['revision']
    refs = {r['id']: r for r in data['references']}
    root_resolved = Path(root).resolve()

    if model == 'wan3':
        units = data.get('generation_groups', [])
        if not isinstance(units, list) or not units:
            rec['requests'][model] = []
            rec['released'][model] = []
            return [], []
    else:
        units = board.display_units(data)
        errors, _ = board.validate(data, source.parent, True)

    requests, released = [], []
    for u in units:
        if model == 'wan3':
            errors_u, _ = board.validate(
                {**data, 'active_model': 'wan3', 'generation_groups': [u]},
                source.parent,
                True,
                highlight_units=units,
            )
        else:
            errors_u = errors
        wan = u.get('model') == 'wan3'
        seedance = u.get('model') == 'seedance2'
        from editing import pending
        needs_sync = pending(u)
        seconds = u['editor_draft']['values'].get('duration_s', u['duration_s']) if needs_sync else u['duration_s']
        prompt = board.model_prompt(u)
        bindings = []
        safe = True
        media_counts = {'picture': 0, 'video': 0}
        for rid in u.get('references', []):
            path = board.resolve(source.parent, refs[rid].get('path') or '')
            if not path.is_relative_to(root_resolved) or not path.is_file():
                safe = False
                continue
            kind = 'video' if refs[rid].get('type') == 'video_reference' else 'picture'
            media_counts[kind] += 1
            binding = {'path': path.relative_to(root_resolved).as_posix(), 'sha256': digest(path), kind + '_index': media_counts[kind]}
            if kind == 'video':
                binding['role'] = 'reference_video'
            bindings.append(binding)
        asset_hash = hashlib.sha256(str(bindings).encode()).hexdigest()[:8]
        uid = entry['id'] + '_' + u['id']
        rid = uid + '-' + source_hash[:10] + '-' + asset_hash
        generation = u.get('generation', {})
        adapted = generation.get('protocol') in ('doubao-canvas-v1', 'scenora-v1') if seedance else not wan or generation.get('protocol') in ('wan-portal-v1', 'scenora-v1')
        item = {
            'request_id': rid, 'episode_id': entry['id'], 'episode_dir': source.parent.relative_to(root_resolved).as_posix(),
            'unit_id': uid, 'source_request_ids': [rid], 'source_board': entry['current_data'],
            'source_board_sha256': source_hash, 'model_request_seconds': seconds,
            'adopted_interval': generation.get('adopted_interval', [0, seconds]),
            'narrative_seconds': generation.get('narrative_seconds', seconds),
            'preset': generation.get('preset', 'reference'),
            'width': generation.get('width', 1280), 'height': generation.get('height', 720), 'prompt': prompt,
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'bindings': bindings,
            'ready': (not errors_u and data['review_status'] == 'user_approved') and safe and not needs_sync and data['aspect_ratio'] == '16:9' and adapted,
            'ready_for_approval': not errors_u and not needs_sync and data['review_status'] in ('reviewed', 'user_approved') and safe and data['aspect_ratio'] == '16:9' and adapted,
            'pending_sync': needs_sync,
            'blocked_reason': '中文已修改，等待同步模型提示词。' if needs_sync else 'Wan3本段尚未配置提交接口。' if wan and not adapted else '',
            'review_status': data['review_status'], 'requested_model': 'seedance2' if seedance else 'wan3' if wan else 'MiniMax-H3',
        }
        if wan:
            item['required_protocol'] = 'wan3-unconfigured'
        if generation.get('protocol'):
            item['required_protocol'] = generation['protocol']
        if 'mute_reference_video' in u:
            item['mute_reference_video'] = u['mute_reference_video']
        requests.append(item)
        if item['ready']:
            released.append(rid)

    rec['requests'][model] = requests
    rec['released'][model] = released
    return requests, released


def workspace_state(root, model=None, project=None):
    entries, issues, requests, released = [], [], [], []
    public_paths = set()
    files = _board_files(root, project=project)
    files_sig = []
    for path in files:
        rec = _load_episode(root, path)
        files_sig.append((str(path), rec['json_sig']))
        if not rec['ok']:
            issues.append(rec['issue'])
            continue
        entries.append(rec['entry'])
        public_paths.update(rec['public_paths'])
        ep_reqs, ep_rel = _build_episode_requests(root, rec, model=model)
        requests.extend(ep_reqs)
        released.extend(ep_rel)
    index_key = (str(Path(root).resolve()), project or '')
    with _CACHE_LOCK:
        _PUBLIC_INDEX[index_key] = (tuple(files_sig), frozenset(public_paths))
    return entries, issues, {'requests': requests, 'reviewed_release_ids': released, 'submission_paused': False, 'issues': issues}


def catalog(root, project=None):
    entries, issues = [], []
    for path in _board_files(root, project=project):
        rec = _load_episode(root, path)
        if rec['ok']:
            entries.append(rec['entry'])
        else:
            issues.append(rec['issue'])
    return entries, issues


def plan(root, model=None, project=None):
    return workspace_state(root, model=model, project=project)[2]


def _find_episode_record(root, eid, project=None):
    root_path = Path(root).resolve()
    for path in _board_files(root_path, project=project):
        if _episode_id(path.relative_to(root_path)) == eid:
            rec = _load_episode(root_path, path)
            if rec['ok']:
                return rec
            raise ValueError('当前剧集制作数据校验未通过：' + str(rec['issue']))
    return None


def episode(root, eid, project=None):
    from editing import public_unit
    rec = _find_episode_record(root, eid, project=project)
    if rec is None:
        raise ValueError('未找到此剧集的制作数据。')
    entry = rec['entry']
    requests, _ = _build_episode_requests(root, rec, model=None)
    units = [public_unit(u, eid) for u in board.display_units(entry['data'])]
    source = rec['source_path']
    root_resolved = Path(root).resolve()
    ref_assets = []
    for ref in (entry['data'].get('references') or []):
        if not isinstance(ref, dict):
            continue
        raw_path = ref.get('path') or ''
        url = ''
        if str(raw_path).strip():
            resolved = board.resolve(source.parent, raw_path)
            if resolved.is_relative_to(root_resolved) and resolved.is_file():
                url = '/project/' + quote(resolved.relative_to(root_resolved).as_posix(), safe='/')
        ref_assets.append({
            'id': ref.get('id', ''),
            'type': ref.get('type', ''),
            'path': raw_path,
            'url': url,
            'purpose': ref.get('purpose', ''),
            'verified': ref.get('verified'),
        })
    return {**entry, 'units': units, 'requests': requests, 'reference_assets': ref_assets}


_ASSET_TYPE_ORDER = {'character_sheet': 0, 'background': 1, 'prop': 2, 'video_reference': 3}


def assets(root, project=None):
    root_resolved = Path(root).resolve()
    grouped = {}
    for path in _board_files(root_resolved, project=project):
        rec = _load_episode(root_resolved, path)
        if not rec['ok']:
            continue
        entry = rec['entry']
        data = entry['data']
        source = rec['source_path']
        unit_by_ref = {}
        for u in board.display_units(data):
            for rid in (u.get('references') or []):
                unit_by_ref.setdefault(rid, []).append(u.get('id', ''))
        for ref in (data.get('references') or []):
            if not isinstance(ref, dict):
                continue
            rid = str(ref.get('id') or '')
            raw_path = str(ref.get('path') or '').strip()
            resolved = board.resolve(source.parent, raw_path) if raw_path else None
            exists = bool(resolved and resolved.is_relative_to(root_resolved) and resolved.is_file())
            rel = resolved.relative_to(root_resolved).as_posix() if exists else raw_path
            key = rel if exists else f'missing:{entry["id"]}:{rid}'
            url = '/project/' + quote(rel, safe='/') if exists else ''
            item = grouped.get(key)
            if item is None:
                item = {
                    'key': key,
                    'id': rid,
                    'ids': [],
                    'type': ref.get('type', 'prop'),
                    'path': rel,
                    'url': url,
                    'purpose': ref.get('purpose', ''),
                    'verified': ref.get('verified'),
                    'width': ref.get('width'),
                    'height': ref.get('height'),
                    'projects': [],
                    'episodes': [],
                }
                grouped[key] = item
            if rid and rid not in item['ids']:
                item['ids'].append(rid)
            proj_name = data.get('project', '')
            if proj_name and proj_name not in item['projects']:
                item['projects'].append(proj_name)
            if ref.get('verified') is True and item['verified'] is not True:
                item['verified'] = True
            if not item['purpose'] and ref.get('purpose'):
                item['purpose'] = ref.get('purpose')
            ep_info = {
                'id': entry['id'],
                'code': data.get('episode', ''),
                'title': data.get('title', ''),
                'project': proj_name,
                'units': unit_by_ref.get(rid, []),
            }
            if not any(ep['id'] == ep_info['id'] for ep in item['episodes']):
                item['episodes'].append(ep_info)
    result = sorted(
        grouped.values(),
        key=lambda a: (_ASSET_TYPE_ORDER.get(a['type'], 9), 0 if a['url'] else 1, a['id'], a['key']),
    )
    return {'assets': result}


def html(root, eid, project=None):
    entry = episode(root, eid, project=project)
    source = Path(root) / entry['current_data']
    # Browser URL /project/<episode folder>/打开看板.html keeps relative asset links correct.
    output = source.with_name('打开看板.html')
    rendered = board.render(entry['data'], source.parent, output, entry['warnings'])
    # Enhance the original board in place only when served by the local studio.
    # Exported/offline HTML and frozen generation records remain unchanged.
    payload = json.dumps({'id': eid, 'title': entry['title'], 'current_data': entry['current_data'],
                          'units': entry['units'], 'requests': entry['requests']}, ensure_ascii=False)
    payload = payload.replace('<', r'\u003c').replace('>', r'\u003e').replace('&', r'\u0026')
    injection = ('<link rel="stylesheet" href="/board-editor.css">'
                 '<script type="application/json" id="board-editor-data">' + payload + '</script>'
                 '<script src="/board-editor.js"></script>')
    return rendered.replace('</body>', injection + '</body>')


def public_file(root, path, project=None):
    """Expose only registered board assets/originals, never keys or task records."""
    root_resolved = Path(root).resolve()
    target = Path(path).resolve()
    scope_root = (root_resolved / project).resolve() if project else root_resolved
    if not target.is_relative_to(scope_root) or not target.is_file():
        return False
    index_key = (str(root_resolved), project or '')
    files = _board_files(root_resolved, project=project)
    files_sig = tuple((str(p), _stat_sig(p)) for p in files)
    with _CACHE_LOCK:
        cached = _PUBLIC_INDEX.get(index_key)
    if cached and cached[0] == files_sig:
        return target in cached[1]
    allowed = set()
    for p in files:
        rec = _load_episode(root_resolved, p)
        if rec['ok']:
            allowed.update(rec['public_paths'])
    frozen = frozenset(allowed)
    with _CACHE_LOCK:
        _PUBLIC_INDEX[index_key] = (files_sig, frozen)
    return target in frozen
