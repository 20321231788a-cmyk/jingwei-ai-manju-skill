"""Read current production truth; own only studio mixes and regeneration records."""
import copy
import hashlib
import json
import math
import re
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

QUEUE = Path(__file__).resolve().parents[1] / 'rb_video_queue'
sys.path.insert(0, str(QUEUE))
from runtime import load_json, save_json, settings
from upstream import DEFAULT_PROFILE, validate_profile, validate_submission
from submission_priority import submission_turn, publish_ready


def mask_secret(secret):
    s = str(secret or '').strip()
    if not s:
        return ''
    if len(s) <= 8:
        return '••••'
    return s[:4] + '••••' + s[-4:]


def _dpapi_protect(raw_bytes):
    if sys.platform != 'win32':
        return raw_bytes
    import ctypes
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(raw_bytes, len(raw_bytes)) if raw_bytes else ctypes.create_string_buffer(1)
    in_blob = DATA_BLOB(len(raw_bytes), buf)
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError('本机凭证加密失败')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(enc_bytes):
    if sys.platform != 'win32':
        return enc_bytes
    import ctypes
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(enc_bytes, len(enc_bytes))
    in_blob = DATA_BLOB(len(enc_bytes), buf)
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise OSError('本机凭证解密失败')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def under(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('文件路径超出项目。')
    return path


def task_order(pair):
    path, row = pair
    for value in (row.get('created_at'), row.get('submitted_at'), (row.get('job') or {}).get('created_at')):
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp(), path.stat().st_mtime_ns
        except (ValueError, TypeError):
            pass
    return path.stat().st_mtime, path.stat().st_mtime_ns


def studio_config(project=None):
    cfg = dict(settings(QUEUE / 'config.json'))
    if project:
        root = Path(cfg['root']).resolve()
        proj_dir = under(root, project)
        if not proj_dir.is_dir():
            raise ValueError('指定的作品目录不存在。')
        home = proj_dir / '制作资料/制作看板'
        cfg.update(project=proj_dir.relative_to(root).as_posix(), home=home, records=home / '历史任务')
    return cfg


class Studio:
    def __init__(self, config=None):
        self.config = config or settings(QUEUE/'config.json')
        self.root = Path(self.config['root']).resolve()
        self.project = self.config.get('project') or None
        if self.project:
            proj_dir = under(self.root, self.project)
            if not proj_dir.is_dir():
                raise ValueError('指定的作品目录不存在。')
            self.project = proj_dir.relative_to(self.root).as_posix()
        self.home = Path(self.config['home']).resolve() if self.config.get('home') else (
            (self.root / self.project / '制作资料/制作看板') if self.project else (self.root / '制作资料/制作看板')
        )
        self.jobs_dir = self.home/'重提任务'
        self.exports_dir = self.home/'导出'
        self.lock = threading.RLock()
        self.keys = {}  # runtime only; keyed by immutable profile hash
        self.cache = None; self.cache_time = 0; self._snap_sig = None
        self._json_cache = {}
        self.health = {'checked_at': None, 'error': None}
        self.profile_file = self.home/'上游配置.json'
        self.credentials_file = self.home/'.credentials.dat'
        self.mix_file = self.home/'剪辑方案.json'
        self.annotations_file = self.home/'审片标注.json'
        for path in (self.jobs_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.profile_file.exists():
            shared = self.root/'制作资料/制作看板/上游配置.json'
            if self.project and shared.is_file():
                try:
                    shared_data = load_json(shared)
                    clean_profiles = [validate_profile(p) for p in shared_data.get('profiles', [])]
                    if clean_profiles:
                        active_id = shared_data.get('active')
                        if not any(p['id'] == active_id for p in clean_profiles):
                            active_id = clean_profiles[0]['id']
                        save_json(self.profile_file, {'active': active_id, 'profiles': clean_profiles})
                except Exception:
                    pass
            if not self.profile_file.exists():
                save_json(self.profile_file, {'active': DEFAULT_PROFILE['id'], 'profiles': [DEFAULT_PROFILE]})
        # Apply a user-selected profile only at service startup; a running older
        # server must never silently drop new profile fields when submitting.
        profiles = load_json(self.profile_file)
        pending_profile = profiles.get('activate_on_restart')
        if pending_profile:
            selected = validate_profile(pending_profile)
            existing = next((p for p in profiles['profiles'] if p['id'] == selected['id']), None)
            if existing is not None and existing != selected:
                raise ValueError('待启用的接口编号已存在且配置不同，未覆盖。')
            if existing is None:
                profiles['profiles'].append(selected)
            profiles['active'] = selected['id']
            profiles.pop('activate_on_restart')
            save_json(self.profile_file, profiles)
        self._load_credentials(profiles)
        if not self.mix_file.exists():
            save_json(self.mix_file, {'mixes': []})
        if not self.annotations_file.exists():
            save_json(self.annotations_file, {'videos': {}, 'units': {}})
        # An interrupted POST is never silently retried after service restart.
        for path in self.jobs_dir.glob('*.json'):
            row = load_json(path)
            if row.get('submission_state') == 'sending':
                row['submission_state'] = 'uncertain'; save_json(path, row)

    def invalidate(self):
        self.cache_time = 0
        self._snap_sig = None

    def plan(self):
        if self.config.get('canonical'):
            from canonical import plan
            return plan(self.root, project=self.project)
        return load_json(self.config['plan_path'])

    def series(self):
        if self.config.get('canonical'):
            from canonical import catalog
            return {'episodes': catalog(self.root, project=self.project)[0]}
        return load_json(self.root/'series.json')

    @staticmethod
    def profile_key(profile):
        return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()

    def _read_cred_store(self):
        if not self.credentials_file.is_file():
            return {'by_id': {}, 'by_hash': {}}
        try:
            plain = _dpapi_unprotect(self.credentials_file.read_bytes())
            raw = json.loads(plain.decode('utf-8'))
            by_id = raw.get('by_id') if isinstance(raw.get('by_id'), dict) else {}
            by_hash = raw.get('by_hash') if isinstance(raw.get('by_hash'), dict) else {}
            return {'by_id': {str(k): str(v) for k, v in by_id.items() if v}, 'by_hash': {str(k): str(v) for k, v in by_hash.items() if v}}
        except Exception:
            return {'by_id': {}, 'by_hash': {}}

    def _write_cred_store(self, store):
        payload = json.dumps(store, ensure_ascii=False).encode('utf-8')
        enc = _dpapi_protect(payload)
        self.credentials_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.credentials_file.with_suffix('.dat.tmp')
        tmp.write_bytes(enc)
        if sys.platform != 'win32':
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
        tmp.replace(self.credentials_file)

    def _load_credentials(self, profiles_state=None):
        store = self._read_cred_store()
        for h, secret in store['by_hash'].items():
            if secret:
                self.keys[h] = secret
        ps = profiles_state if profiles_state is not None else (load_json(self.profile_file) if self.profile_file.is_file() else {'profiles': []})
        for p in ps.get('profiles', []):
            sec = store['by_id'].get(p.get('id', ''))
            if sec:
                self.keys[self.profile_key(p)] = sec

    def _persist_credential(self, profile_id=None, profile_hash=None, secret=None, remove_id=None, remove_hash=None):
        store = self._read_cred_store()
        if remove_id:
            store['by_id'].pop(remove_id, None)
        if remove_hash:
            store['by_hash'].pop(remove_hash, None)
        if secret:
            if profile_id:
                store['by_id'][profile_id] = secret
            if profile_hash:
                store['by_hash'][profile_hash] = secret
        # Prune orphaned by_hash entries when self.keys removed them
        if remove_hash:
            for k in list(store['by_hash']):
                if k not in self.keys:
                    store['by_hash'].pop(k, None)
        self._write_cred_store(store)

    def _has_active_jobs(self, profile):
        if not profile:
            return False
        target_hash = self.profile_key(profile)
        for p in self.jobs_dir.glob('*.json'):
            row = self._cached_json(p)
            up = row.get('upstream')
            if not isinstance(up, dict):
                continue
            if self.profile_key(up) == target_hash or up == profile:
                if row.get('submission_state') not in ('failed', 'cancelled', 'rejected') and (row.get('job') or {}).get('status') not in ('done', 'failed', 'cancelled'):
                    return True
        return False

    def _resolve_secret(self, profile, raw_key):
        secret = str(raw_key or '').strip()
        limit = 16384 if profile['protocol'] == 'doubao-canvas-v1' else 512
        if len(secret) > limit or '\n' in secret or '\r' in secret:
            raise ValueError('密钥格式无效。')
        if not secret:
            state = load_json(self.profile_file)
            previous = next((p for p in state.get('profiles', []) if p['id'] == profile['id']), None)
            if previous and previous.get('base_url') == profile['base_url'] and previous.get('protocol') == profile['protocol']:
                secret = self.keys.get(self.profile_key(previous)) or ''
            if not secret:
                same_dest = next(
                    (p for p in state.get('profiles', []) if p.get('base_url') == profile['base_url'] and self.profile_key(p) in self.keys),
                    None,
                )
                if same_dest:
                    secret = self.keys.get(self.profile_key(same_dest)) or ''
        return secret

    def profiles(self):
        value = load_json(self.profile_file)
        enriched = []
        for p in value.get('profiles', []):
            sec = self.keys.get(self.profile_key(p), '')
            enriched.append({**p, 'credential_ready': bool(sec), 'key_masked': mask_secret(sec)})
        value['profiles'] = enriched
        return value

    def save_profile(self, data):
        raw_profile = dict(data['profile'])
        with self.lock:
            state = load_json(self.profile_file)
            previous = next((p for p in state['profiles'] if p['id'] == raw_profile.get('id')), None)
            # Only inherit previous protocol/paths when base_url is unchanged and frontend did not send protocol
            if previous and not raw_profile.get('protocol') and str(raw_profile.get('base_url') or '').rstrip('/') == previous.get('base_url'):
                raw_profile['protocol'] = previous['protocol']
                for k in ('jobs_path', 'presign_path', 'commit_path', 'video_path'):
                    if not raw_profile.get(k):
                        raw_profile[k] = previous.get(k)
            profile = validate_profile(raw_profile)
            secret = str(data.get('key') or '').strip()
            if len(secret) > (16384 if profile['protocol'] == 'doubao-canvas-v1' else 512) or '\n' in secret or '\r' in secret:
                raise ValueError('卡密格式无效。')
            prev_hash = self.profile_key(previous) if previous else None
            previous_key = self.keys.get(prev_hash) if previous else None
            reusable_key = previous_key if previous and previous['base_url'] == profile['base_url'] and previous['protocol'] == profile['protocol'] else None
            if profile['protocol'] == 'doubao-canvas-v1' and data.get('open_session') is True and not secret and not reusable_key:
                from doubao_canvas import new_session_key
                # Explicit initialization only. Never replace an old session to bypass limits.
                if previous and any(r.get('upstream') == previous and
                        (r.get('prepared_submission') or r.get('submitted_at') or r.get('job')) for _, r in self.rows()):
                    raise ValueError('此接口已有任务，请恢复原会话；不能自动换游客身份继续提交。')
                secret = new_session_key()
            account_changed = bool(secret and previous_key and secret != previous_key)
            has_active = self._has_active_jobs(previous) if previous else False
            if previous and has_active and (previous != profile or account_changed):
                # Retain the old selectable configuration only while active jobs depend on it.
                profile['id'] = profile['id'][:42] + '-' + uuid.uuid4().hex[:8]
                if profile['name'] == previous['name']:
                    profile['name'] += ' · ' + datetime.now().strftime('%H:%M:%S')
                state['profiles'] = state['profiles'] + [profile]
            elif previous:
                # Update existing profile cleanly in place without creating duplicates.
                state['profiles'] = [profile if p['id'] == previous['id'] else p for p in state['profiles']]
                if prev_hash and prev_hash != self.profile_key(profile):
                    self.keys.pop(prev_hash, None)
            else:
                state['profiles'] = state['profiles'] + [profile]
            state['active'] = profile['id']
            save_json(self.profile_file, state)
            final_secret = secret or reusable_key or ''
            new_hash = self.profile_key(profile)
            if final_secret:
                self.keys[new_hash] = final_secret
                self._persist_credential(
                    profile_id=profile['id'],
                    profile_hash=new_hash,
                    secret=final_secret,
                    remove_hash=(prev_hash if (previous and not has_active and prev_hash != new_hash) else None),
                )
            elif previous and not has_active:
                self.keys.pop(new_hash, None)
                self._persist_credential(remove_id=profile['id'], remove_hash=prev_hash)
        return self.profiles()

    def delete_profile(self, data):
        pid = str((data or {}).get('id') or '').strip()
        if not pid:
            raise ValueError('请指定要删除的接口编号。')
        with self.lock:
            state = load_json(self.profile_file)
            target = next((p for p in state.get('profiles', []) if p['id'] == pid), None)
            if not target:
                raise ValueError('未找到要删除的接口配置。')
            state['profiles'] = [p for p in state['profiles'] if p['id'] != pid]
            if state.get('active') == pid:
                state['active'] = state['profiles'][0]['id'] if state['profiles'] else ''
            save_json(self.profile_file, state)
            target_hash = self.profile_key(target)
            still_used = any(self.profile_key(p) == target_hash for p in state['profiles']) or self._has_active_jobs(target)
            if not still_used:
                self.keys.pop(target_hash, None)
            self._persist_credential(remove_id=pid, remove_hash=(None if still_used else target_hash))
        return self.profiles()

    def fetch_models(self, data, fetcher=None):
        from upstream import fetch_upstream_models
        raw_profile = dict((data or {}).get('profile') or {})
        if (data or {}).get('base_url') and not raw_profile.get('base_url'):
            raw_profile['base_url'] = data['base_url']
        raw_profile.setdefault('id', 'probe-models')
        raw_profile.setdefault('name', '临时查询')
        if not str(raw_profile.get('model') or '').strip() and not isinstance(raw_profile.get('preset_map'), dict):
            raw_profile['model'] = 'reference'
        profile = validate_profile(raw_profile)
        secret = self._resolve_secret(profile, (data or {}).get('key'))
        if not secret:
            raise ValueError('请先输入此接口的密钥，再向上游获取模型。')
        try:
            models = (fetcher or fetch_upstream_models)(profile, secret)
        except ValueError as error:
            msg = str(error).replace(secret, '[redacted]') if secret else str(error)
            raise ValueError(msg) from None
        except Exception:
            raise ValueError('暂时无法从该上游获取模型，请检查接口地址与密钥。') from None
        return {
            'ok': True,
            'models': models,
            'detected_protocol': profile['protocol'],
            'message': f'已从上游获取 {len(models)} 个可用模型。',
        }

    def test_profile(self, data, client_factory=None):
        from upstream import UpstreamError, client_type
        profile = validate_profile(data['profile'])
        secret = self._resolve_secret(profile, data.get('key'))
        if not secret:
            raise ValueError('请先输入此接口的密钥，再测试连接。')
        factory = client_factory or client_type(profile)
        client = factory(profile, secret)
        try:
            if profile['protocol'] == 'doubao-canvas-v1':
                client.check()
            if profile['protocol'] == 'openai-video-v1' and client_factory is None:
                models = client.models()
                return {'ok': True, 'message': f'连接成功，上游返回 {len(models)} 个可用模型。本次测试未生成视频。', 'models': models}
            client.jobs()
            return {'ok': True, 'message': '连接成功，任务查询正常。本次测试未生成视频。'}
        except UpstreamError as error:
            raise ValueError(f'接口返回HTTP {error.status}，请检查地址和密钥。') from None
        except ValueError as error:
            msg = str(error).replace(secret, '[redacted]') if secret else str(error)
            raise ValueError(msg) from None
        except Exception:
            raise ValueError('暂时无法连接此接口，请检查网络和接口地址后重试。') from None
        finally:
            client.close()

    def _cached_json(self, path):
        st = path.stat()
        key = str(path)
        sig = (st.st_mtime_ns, st.st_size)
        cached = self._json_cache.get(key)
        if cached is not None and cached[0] == sig:
            return cached[1]
        data = load_json(path)
        self._json_cache[key] = (sig, data)
        return data

    def rows(self):
        rows = []
        for directory in (self.config['records'], self.jobs_dir):
            for path in directory.glob('*.json'):
                row = self._cached_json(path)
                rows.append((path, row))
        return rows

    def video_rows(self):
        # Read registered downloads, never infer completion from the presence of a .part file.
        all_rows = self.rows()
        legacy = self.root/'制作资料/全剧API时长适配'
        for directory in legacy.glob('*/任务记录'):
            all_rows.extend((p, self._cached_json(p)) for p in directory.glob('*.json'))
        found = {}
        root_str = str(self.root.resolve())
        for path, row in all_rows:
            rel = (row.get('download') or {}).get('path')
            if not rel:
                continue
            target = under(self.root, rel)
            try:
                st = target.stat()
            except OSError:
                continue
            if not target.suffix.lower() == '.mp4' or not target.is_file():
                continue
            if self.project and not target.is_relative_to(self.root / self.project):
                continue
            vid = hashlib.sha256(str(target).encode()).hexdigest()[:24]
            found[vid] = {'id': vid, 'path': target.relative_to(self.root).as_posix(),
                          'request_id': row['request_id'], 'unit_id': row.get('unit_id'),
                          'episode_id': row.get('episode_id'), 'source_request_ids': row.get('source_request_ids', []),
                          'seconds': row.get('model_request_seconds') or (row.get('request') or {}).get('seconds') or 15,
                          'adopted_interval': row.get('adopted_interval'),
                          'mtime': st.st_mtime, 'size': st.st_size,
                          'upstream': (row.get('upstream') or {}).get('name', '原提交记录'),
                           'prompt_sha256': (row.get('source_item') or {}).get('prompt_sha256'),
                          'url': '/media/' + vid}
        return sorted(found.values(), key=lambda x: x['mtime'], reverse=True)

    def snapshot(self, force=False):
        with self.lock:
            if self.config.get('canonical'):
                from canonical import workspace_state
                entries, _, plan = workspace_state(self.root, project=self.project)
                series = {'episodes': entries}
                snap_sig = (
                    tuple((e['id'], e['revision']) for e in entries),
                    len(plan['requests']),
                    tuple(sorted(self.health.items())),
                    tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for directory in (self.config['records'], self.jobs_dir) for p in sorted(directory.glob('*.json'))),
                )
                if not force and self.cache and self._snap_sig == snap_sig:
                    return self.cache
            else:
                if not force and self.cache and time.monotonic()-self.cache_time < 4:
                    return self.cache
                plan = self.plan(); series = self.series()
                snap_sig = None
            rows = sorted(self.rows(), key=task_order, reverse=True)
            videos = self.video_rows(); existing_videos = {v['request_id'] for v in videos}
            def task(path, row):
                state = (row.get('job') or {}).get('status') or row.get('submission_state') or 'queued'
                if row.get('submission_state') in ('queued', 'waiting_key', 'retry_wait', 'capacity_wait', 'uncertain', 'sending', 'rejected', 'failed', 'cancelled'):
                    state = row['submission_state']
                downloaded = row['request_id'] in existing_videos
                return {'request_id': row['request_id'], 'episode_id': row.get('episode_id'), 'unit_id': row.get('unit_id'),
                        'seconds': row.get('model_request_seconds') or (row.get('request') or {}).get('seconds') or 15,
                        'state': 'done' if downloaded else state, 'downloaded': downloaded,
                        'job_id': (row.get('job') or {}).get('id'), 'attempts': len(row.get('attempts', [])),
                        'source': 'studio' if path.parent == self.jobs_dir else 'agent',
                        'upstream': (row.get('upstream') or {}).get('name', '原提交记录'),
                        'created_at': row.get('created_at') or row.get('submitted_at') or '', 'note': row.get('note', '')}

            tasks, selected = [], set()
            unit_counts = Counter((q['episode_id'], q['unit_id']) for q in plan['requests'])
            for item in plan['requests']:
                # Request IDs change with storyboard revisions. A canonical unit is
                # the stable shot identity; old split requests retain their lineage.
                def belongs(row):
                    if row['request_id'] == item['request_id'] or row.get('retry_of') == item['request_id']:
                        return True
                    if (row.get('episode_id'), row.get('unit_id')) != (item['episode_id'], item['unit_id']):
                        return False
                    if set(row.get('source_request_ids', [])).intersection(item.get('source_request_ids', [])):
                        return True
                    return self.config.get('canonical') and unit_counts[(item['episode_id'], item['unit_id'])] == 1
                candidates = [(p, r) for p, r in rows if r['request_id'] not in selected and belongs(r)]
                superseded = {r.get('retry_of') for _, r in candidates}
                latest = next(((p, r) for p, r in candidates if r['request_id'] not in superseded), None)
                if latest:
                    current = task(*latest)
                    current['plan_request_id'] = item['request_id']
                    selected.add(current['request_id'])
                    tasks.append(current)
                    continue
                default_state = ('ready' if item.get('ready') else 'draft') if self.config.get('canonical') else 'queued'
                tasks.append({'request_id': item['request_id'], 'plan_request_id': item['request_id'],
                              'episode_id': item['episode_id'], 'unit_id': item['unit_id'],
                              'seconds': item['model_request_seconds'], 'state': default_state, 'downloaded': False,
                              'job_id': None, 'attempts': 0, 'source': 'agent', 'upstream': '待选择接口'})
            history = [task(p, r) for p, r in rows if r['request_id'] not in selected]
            regen = [task(p, r) for p, r in rows if p.parent == self.jobs_dir]
            episodes = []
            for e in series['episodes']:
                subset = [t for t in tasks if t['episode_id'] == e['id']]
                episodes.append({'id': e['id'], 'title': e['title'], 'shots': e.get('shot_count', 0),
                                 'revision': e.get('revision'),
                                 'total': len(subset), 'downloaded': sum(t['downloaded'] for t in subset),
                                 'video_count': sum(v['episode_id']==e['id'] for v in videos),
                                 'board': '/board/'+e['id'], 'in_plan': bool(subset)})
            counts = Counter(t['state'] for t in tasks)
            self.cache = {'updated_at': stamp(), 'episodes': episodes, 'tasks': tasks, 'history': history, 'regenerations': regen,
                          'videos': videos, 'counts': dict(counts), 'total': len(tasks),
                          'downloaded': sum(t['downloaded'] for t in tasks), 'plan_paused': plan.get('submission_paused'),
                          'issues': plan.get('issues', []),
                          'health': dict(self.health)}
            self._snap_sig = snap_sig
            self.cache_time = time.monotonic()
            return self.cache

    def video(self, vid):
        value = next((v for v in self.snapshot()['videos'] if v['id'] == vid), None)
        if not value:
            raise ValueError('视频不存在或尚未下载完成，请刷新后重试。')
        return value

    def episode(self, eid):
        if self.config.get('canonical'):
            from canonical import episode
            return episode(self.root, eid, project=self.project)
        if not re.fullmatch(r'EP\d{3}', eid):
            raise ValueError('集数无效。')
        series = load_json(self.root/'series.json')
        entry = next((e for e in series['episodes'] if e['id']==eid), None)
        if not entry:
            raise ValueError('未找到该集。')
        board = load_json(under(self.root, entry['current_data']))
        requests = [q for q in self.plan()['requests'] if q['episode_id']==eid]
        return {'id': eid, 'title': entry['title'], 'units': board['units'], 'requests': requests,
                'delivery_board': entry.get('delivery_board')}

    def validate_mix(self, data):
        mid = str(data.get('id') or uuid.uuid4().hex)
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', mid):
            raise ValueError('剪辑方案编号无效。')
        clips = data.get('clips', [])
        if not isinstance(clips, list) or len(clips)>100:
            raise ValueError('每个方案最多 100 个片段。')
        clean = []
        for c in clips:
            v = self.video(c['video_id']); start=float(c['start']); end=float(c['end'])
            if not math.isfinite(start+end) or not 0 <= start < end or end > float(v['seconds'])+0.1 or end-start<0.1:
                raise ValueError('剪辑起止时间无效，须在素材时长以内且至少 0.1 秒。')
            clean.append({'video_id': v['id'], 'start': round(start,3), 'end': round(end,3)})
        return {'id': mid, 'name': str(data.get('name') or '未命名方案').strip()[:100],
                'episode_id': str(data.get('episode_id') or ''), 'clips': clean, 'updated_at': stamp()}

    def save_mix(self, data):
        with self.lock:
            mix = self.validate_mix(data); state = load_json(self.mix_file)
            state['mixes'] = [m for m in state['mixes'] if m['id'] != mix['id']] + [mix]
            save_json(self.mix_file, state)
            return mix

    def annotations(self):
        with self.lock:
            raw = load_json(self.annotations_file) if self.annotations_file.exists() else {}
            videos = raw.get('videos') if isinstance(raw.get('videos'), dict) else {}
            units = raw.get('units') if isinstance(raw.get('units'), dict) else {}
            return {'videos': videos, 'units': units}

    def save_annotation(self, data):
        kind = str(data.get('kind') or '')
        if kind not in ('video', 'unit'):
            raise ValueError('标注类型无效。')
        target_id = str(data.get('id') or '').strip()
        if not 1 <= len(target_id) <= 128:
            raise ValueError('标注目标编号无效。')
        note = str(data.get('note') or '').strip()[:200]
        with self.lock:
            state = self.annotations()
            if kind == 'video':
                tag = str(data.get('tag') or '')
                if tag not in ('', 'star', 'bad'):
                    raise ValueError('视频标记无效。')
                if not tag and not note:
                    state['videos'].pop(target_id, None)
                else:
                    state['videos'][target_id] = {'tag': tag, 'note': note, 'updated_at': stamp()}
            else:
                review = str(data.get('review') or '')
                if review not in ('', 'ok', 'fix'):
                    raise ValueError('审阅标记无效。')
                if not review and not note:
                    state['units'].pop(target_id, None)
                else:
                    state['units'][target_id] = {'review': review, 'note': note, 'updated_at': stamp()}
            save_json(self.annotations_file, state)
            return state

    def assets(self):
        if self.config.get('canonical'):
            from canonical import assets as canonical_assets
            return canonical_assets(self.root, project=self.project)
        return {'assets': []}

    def regenerate(self, data):
        with self.lock:
            nonce = str(data.get('nonce', ''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{12,80}', nonce):
                raise ValueError('重提请求缺少有效的防重复编号。')
            prior = [r for p,r in self.rows() if p.parent==self.jobs_dir and r.get('nonce')==nonce]
            if prior:
                return {'request_ids': [r['request_id'] for r in prior], 'reused': True}
            if self.config.get('canonical') and data.get('model'):
                from canonical import plan as canonical_plan
                plan = canonical_plan(self.root, model=data.get('model'), project=self.project)
            else:
                plan = self.plan()
            wanted = data.get('request_ids', [])
            if not isinstance(wanted, list) or not wanted or len(set(wanted)) != len(wanted):
                raise ValueError('请选择本集需要重提的镜头。')
            items = [q for q in plan['requests'] if q['request_id'] in wanted]
            if len(items)!=len(wanted) or len({q['episode_id'] for q in items})!=1:
                raise ValueError('一次只能重提当前计划中同一集的镜头。')
            releases=set(plan.get('reviewed_release_ids', []))
            selected_approved = data.get('approve_reviewed_selection') is True
            if any(q.get('pending_sync') for q in items):
                raise ValueError('中文修改尚未同步英文提示词，请先完成同步后再提交。')
            if any(q['request_id'] not in releases and not (selected_approved and q.get('ready_for_approval')) for q in items):
                raise ValueError('包含尚未用户终审通过、缺少完整正文或真实参考图的镜头；先完成同一份制作数据后再提交。')
            profile = next((p for p in load_json(self.profile_file)['profiles'] if p['id']==data.get('profile_id')), None)
            if not profile or self.profile_key(profile) not in self.keys:
                raise ValueError('请先选择上游并输入本次卡密。卡密只在本地服务内存保存。')
            profile=validate_profile(profile)
            if profile['protocol'] != 'sparkcine-v1' and any(
                    b.get('role', 'reference_image') != 'reference_image' for q in items for b in q['bindings']):
                raise ValueError('该接口尚未实现视频参考，请选择支持全能视频参考的接口。')
            # Freeze exactly the reviewed prompt and references; no edits or implicit conversions.
            for q in items:
                validate_submission(profile, q)
                if hashlib.sha256(under(self.root,q['source_board']).read_bytes()).hexdigest()!=q['source_board_sha256']:
                    raise ValueError('制作数据已经变化，请由 agent 同步计划后重提。')
                if hashlib.sha256(q['prompt'].encode()).hexdigest()!=q['prompt_sha256']:
                    raise ValueError('提示词校验失败。')
                if q['model_request_seconds']==20 and (len(q['prompt'].split('\n------\n'))!=2):
                    raise ValueError('20 秒请求必须保留两个 10 秒段。')
                for b in q['bindings']:
                    if hashlib.sha256(under(self.root,b['path']).read_bytes()).hexdigest()!=b['sha256']:
                        raise ValueError('参考图已经变化，请由 agent 更新计划。')
            busy = [r for p,r in self.rows() if p.parent==self.jobs_dir and r['submission_state'] not in ('failed','cancelled','rejected')
                    and (r.get('job') or {}).get('status') not in ('done','failed','cancelled')
                    and ((r.get('upstream') or {}).get('protocol') == profile['protocol']
                         and (r.get('upstream') or {}).get('base_url') == profile['base_url'])]
            if any(r.get('retry_of') in wanted or self.config.get('canonical') and
                   any((r.get('episode_id'), r.get('unit_id')) == (q['episode_id'], q['unit_id']) for q in items) for r in busy):
                raise ValueError('所选镜头已有看板重提任务在途，请等待该任务完成。')
            with submission_turn(self.root, home_dir=self.home):
                publish_ready(self.root,list(self.keys),home_dir=self.home)
                results=[]
                for i,q in enumerate(items):
                    rid = q['unit_id']+'-studio-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
                    row = {k:copy.deepcopy(q[k]) for k in ('episode_id','unit_id','source_request_ids','model_request_seconds','adopted_interval')}
                    row.update(request_id=rid, retry_of=q['request_id'], nonce=nonce, upstream=profile,
                               source_item=copy.deepcopy(q), submission_state='queued', created_at=datetime.now().astimezone().isoformat(timespec='microseconds'), job=None, order=i, priority=100, note='已进入优先队列，等待下一个空闲名额。')
                    if selected_approved and q['request_id'] not in releases:
                        row['user_approval_scope'] = '本次选中镜头'
                    save_json(self.jobs_dir/(rid+'.json'),row); results.append(rid)
            self.invalidate()
            return {'request_ids': results, 'reused': False}
