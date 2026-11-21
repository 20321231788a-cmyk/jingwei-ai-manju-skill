"""Upstream adapters. Profile snapshots contain no credentials."""
import base64
import hashlib
import math
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

DEFAULT_PROFILE = {
    'id': 'rb-default', 'name': '当前 RB 上游', 'base_url': 'https://rb.coolhs.com',
    'protocol': 'rb-v1', 'jobs_path': '/api/v1/jobs',
    'presign_path': '/api/v1/uploads/presign', 'commit_path': '/api/v1/uploads/commit',
    'video_path': '/api/v1/jobs/{id}/video?download=1', 'max_concurrency': 5,
    'preset_map': {'reference': 'reference', 'easy_15': 'easy_15', 'dmad_20': 'dmad_20', 'dmad_30': 'dmad_30'},
}

SUPPORTED_PROTOCOLS = ('rb-v1', 'sparkcine-v1', 'wan-portal-v1', 'doubao-canvas-v1', 'scenora-v1', 'openai-video-v1')

VIDEO_MODEL_HINTS = (
    'wan', 'seedance', 'h3', 'kling', 'vidu', 'sora', 'veo', 'hailuo',
    'minimax', 'jimeng', 'runway', 'luma', 'pika', 'video', 'cogvideo', 'pixverse', 'grok',
)


def api_join(base_url, rel_path):
    base = str(base_url or '').rstrip('/')
    rel = '/' + str(rel_path or '').lstrip('/')
    base_path = urlsplit(base).path.rstrip('/')
    if base_path.endswith('/v1') and (rel == '/v1' or rel.startswith('/v1/')):
        rel = rel[3:] or '/'
    return base + rel


def infer_protocol(base_url):
    host = (urlsplit(str(base_url or '')).hostname or '').lower()
    if host == 'scenora.ink' or host.endswith('.scenora.ink'):
        return 'scenora-v1'
    if host == 'hi.hi.run' or host.endswith('.hi.run'):
        return 'sparkcine-v1'
    if host == 'wan.coolhs.com':
        return 'wan-portal-v1'
    if host == 'rb.coolhs.com':
        return 'rb-v1'
    if host == 'www.doubao.com':
        return 'doubao-canvas-v1'
    return 'openai-video-v1'


def protocol_defaults(protocol):
    if protocol == 'scenora-v1':
        return {
            'jobs_path': '/v1/videos/generations',
            'presign_path': '/v1/assets',
            'commit_path': '/v1/assets',
            'video_path': '/v1/videos/{id}/content',
            'max_concurrency': 5,
            'video_resolution': '1080p',
        }
    if protocol == 'sparkcine-v1':
        return {
            'jobs_path': '/api/open/v1/generations',
            'presign_path': '/api/open/v1/uploads',
            'commit_path': '/api/open/v1/uploads/{id}/complete',
            'video_path': '/api/open/v1/generations/{id}',
            'max_concurrency': 150,
            'video_resolution': '720p',
        }
    if protocol == 'wan-portal-v1':
        return {
            'jobs_path': '/api/portal/jobs',
            'presign_path': '/api/portal/media/presign',
            'commit_path': '/api/portal/media/commit',
            'video_path': '/api/portal/jobs/{id}/video?dl=1',
            'max_concurrency': 10,
            'video_resolution': '1080P',
        }
    if protocol == 'doubao-canvas-v1':
        return {
            'jobs_path': '/creativity/canvas_workspace/doc/get',
            'presign_path': '/alice/resource/prepare_upload',
            'commit_path': '/alice/resource/register',
            'video_path': '/creativity/resource/{id}',
            'max_concurrency': 1,
        }
    if protocol == 'openai-video-v1':
        return {
            'jobs_path': '/v1/videos',
            'presign_path': '/v1/files',
            'commit_path': '/v1/files',
            'video_path': '/v1/videos/{id}/content',
            'max_concurrency': 10,
            'video_resolution': '1080p',
        }
    return {
        'jobs_path': '/api/v1/jobs',
        'presign_path': '/api/v1/uploads/presign',
        'commit_path': '/api/v1/uploads/commit',
        'video_path': '/api/v1/jobs/{id}/video?download=1',
        'max_concurrency': 5,
    }

WAN_PROFILE = {
    'id': 'wan-coolhs', 'name': '万万工作台 · Wan3 · 1080P', 'base_url': 'https://wan.coolhs.com',
    'protocol': 'wan-portal-v1', 'jobs_path': '/api/portal/jobs',
    'presign_path': '/api/portal/media/presign', 'commit_path': '/api/portal/media/commit',
    'video_path': '/api/portal/jobs/{id}/video?dl=1', 'max_concurrency': 10,
    'video_resolution': '1080P',
    'preset_map': {'reference': 'wan3', 'easy_15': 'wan3', 'dmad_20': 'wan3', 'dmad_30': 'wan3'},
}

DOUBAO_PROFILE = {
    'id': 'doubao-canvas', 'name': '豆包画布 · Seedance 2.0 · 15秒',
    'base_url': 'https://www.doubao.com', 'protocol': 'doubao-canvas-v1',
    'jobs_path': '/creativity/canvas_workspace/doc/get',
    'presign_path': '/alice/resource/prepare_upload', 'commit_path': '/alice/resource/register',
    'video_path': '/creativity/resource/{id}', 'max_concurrency': 1,
    'preset_map': {'reference': 'seedance2', 'easy_15': 'seedance2', 'dmad_20': 'seedance2', 'dmad_30': 'seedance2'},
}

SCENORA_WAN3_PRO_PROFILE = {
    'id': 'scenora-wan3-pro', 'name': '映流 Scenora · Wan 3.0 Pro · 30秒 1080p',
    'base_url': 'https://scenora.ink', 'protocol': 'scenora-v1',
    'jobs_path': '/v1/videos/generations', 'presign_path': '/v1/assets',
    'commit_path': '/v1/assets', 'video_path': '/v1/videos/{id}/content',
    'max_concurrency': 5, 'video_resolution': '1080p',
    'preset_map': {'reference': 'wan3-pro', 'easy_15': 'wan3-pro', 'dmad_20': 'wan3-pro', 'dmad_30': 'wan3-pro'},
}

SCENORA_SEEDANCE_FACE_PROFILE = {
    'id': 'scenora-seedance-face', 'name': '映流 Scenora · Seedance不卡脸 · 15秒 720p',
    'base_url': 'https://scenora.ink', 'protocol': 'scenora-v1',
    'jobs_path': '/v1/videos/generations', 'presign_path': '/v1/assets',
    'commit_path': '/v1/assets', 'video_path': '/v1/videos/{id}/content',
    'max_concurrency': 10, 'video_resolution': '720p',
    'preset_map': {'reference': 'seedance-2.0-face', 'easy_15': 'seedance-2.0-face', 'dmad_20': 'seedance-2.0-face', 'dmad_30': 'seedance-2.0-face'},
}

SCENORA_SEEDANCE_FULL_PROFILE = {
    **SCENORA_SEEDANCE_FACE_PROFILE,
    'id': 'scenora-seedance-full-5pt',
    'name': '映流 Scenora · Seedance 2.0 · 15秒 720p · 5积分',
    'preset_map': dict.fromkeys(SCENORA_SEEDANCE_FACE_PROFILE['preset_map'], 'seedance-2.0-full'),
    'max_price_units': 500,
}


def validate_profile(data):
    raw = dict(data or {})
    p = {k: raw.get(k, v) for k, v in DEFAULT_PROFILE.items()}
    p['id'] = str(p['id'])
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', p['id']):
        raise ValueError('接口编号只能使用字母、数字、横线和下划线。')
    p['name'] = str(p['name']).strip()[:80]
    if not p['name']:
        raise ValueError('请填写接口名称。')
    p['base_url'] = str(p['base_url']).strip().rstrip('/')
    u = urlsplit(p['base_url'])
    is_loopback = u.scheme == 'http' and (u.hostname in ('127.0.0.1', 'localhost'))
    if (u.scheme != 'https' and not is_loopback) or not u.netloc or u.username or u.password or u.query or u.fragment:
        raise ValueError('上游地址须为不含卡密或查询参数的 HTTPS 地址（或本机测试地址）。')

    explicit_protocol = raw.get('protocol')
    if explicit_protocol is None or str(explicit_protocol).strip() == '' or str(explicit_protocol).strip() == 'auto':
        p['protocol'] = infer_protocol(p['base_url'])
    else:
        p['protocol'] = str(explicit_protocol).strip()
    if p['protocol'] not in SUPPORTED_PROTOCOLS:
        raise ValueError('尚未安装该接口协议的适配器，未发送请求。')

    defaults = protocol_defaults(p['protocol'])
    for k in ('jobs_path', 'presign_path', 'commit_path', 'video_path'):
        if k not in raw or not str(raw.get(k) or '').strip():
            p[k] = defaults[k]
    if 'max_concurrency' not in raw or raw.get('max_concurrency') in (None, ''):
        p['max_concurrency'] = defaults['max_concurrency']

    if p['protocol'] == 'doubao-canvas-v1' and p['base_url'] != 'https://www.doubao.com':
        raise ValueError('豆包画布会话只能发送给 https://www.doubao.com。')
    if p['protocol'] == 'sparkcine-v1' and 'video_resolution' in raw and raw['video_resolution'] not in (None, ''):
        p['video_resolution'] = str(raw['video_resolution']).lower()
        if p['video_resolution'] not in ('720p', '768p', '1080p'):
            raise ValueError('SparkCine 本配置支持 720p、768p 或 1080p。')
    if p['protocol'] == 'scenora-v1':
        p['video_resolution'] = str(raw.get('video_resolution') or '1080p').lower()
        if p['video_resolution'] not in ('480p', '720p', '1080p'):
            raise ValueError('映流 Scenora 支持 480p、720p 或 1080p。')
        if 'max_price_units' in raw:
            limit = raw['max_price_units']
            if type(limit) is not int or limit < 1:
                raise ValueError('映流 Scenora 单条积分上限须为正整数计费单位。')
            p['max_price_units'] = limit
    if p['protocol'] == 'wan-portal-v1':
        p['video_resolution'] = str(raw.get('video_resolution') or '1080P').upper()
        if p['video_resolution'] not in ('480P', '720P', '1080P'):
            raise ValueError('Wan接口支持480P、720P或1080P。')
    if p['protocol'] == 'openai-video-v1':
        p['video_resolution'] = str(raw.get('video_resolution') or '1080p').lower()
        if p['video_resolution'] not in ('480p', '720p', '768p', '1080p'):
            raise ValueError('分辨率须为 480p、720p、768p 或 1080p。')
    elif p['protocol'] == 'rb-v1' and raw.get('video_resolution') not in (None, ''):
        p['video_resolution'] = str(raw['video_resolution']).lower()
        if p['video_resolution'] not in ('480p', '720p', '768p', '1080p'):
            raise ValueError('分辨率须为 480p、720p、768p 或 1080p。')

    for key in ('jobs_path', 'presign_path', 'commit_path', 'video_path'):
        value = str(p[key]).strip()
        if not value.startswith('/') or value.startswith('//') or '://' in value or '\\' in value or '#' in value:
            raise ValueError('接口路径必须是同一上游的相对路径。')
        p[key] = value
    if '{id}' not in p['video_path']:
        raise ValueError('视频下载路径必须包含 {id}。')
    p['max_concurrency'] = int(p['max_concurrency'])
    maximum = (
        2000 if p['protocol'] == 'wan-portal-v1'
        else 150 if p['protocol'] == 'sparkcine-v1'
        else 100 if p['protocol'] in ('scenora-v1', 'openai-video-v1')
        else 1 if p['protocol'] == 'doubao-canvas-v1'
        else 5
    )
    if not 1 <= p['max_concurrency'] <= maximum:
        raise ValueError(f'该接口并发上限为 1–{maximum}。')

    has_explicit_model = 'model' in raw and raw.get('model') is not None and str(raw.get('model')).strip() != ''
    if has_explicit_model:
        model_id = str(raw['model']).strip()
        if len(model_id) > 120:
            raise ValueError('模型标识长度不能超过 120 个字符。')
        p['model'] = model_id
        if 'preset_map' not in raw or not isinstance(raw.get('preset_map'), dict):
            p['preset_map'] = {k: model_id for k in DEFAULT_PROFILE['preset_map']}
        else:
            p['preset_map'] = {**raw['preset_map'], 'reference': model_id}
    elif p['protocol'] == 'openai-video-v1':
        ref_val = (p.get('preset_map') or {}).get('reference') if isinstance(p.get('preset_map'), dict) else ''
        if not isinstance(ref_val, str) or not ref_val.strip():
            raise ValueError('请选择或填写要使用的视频模型。')
        p['model'] = ref_val.strip()

    if not isinstance(p['preset_map'], dict) or set(p['preset_map']) != set(DEFAULT_PROFILE['preset_map']):
        raise ValueError('须提供四个已有预设的名称映射。')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 120 for v in p['preset_map'].values()):
        raise ValueError('预设名称无效。')

    avail = raw.get('available_models')
    if isinstance(avail, list) and avail:
        seen = []
        for item in avail[:300]:
            m = item.get('id') if isinstance(item, dict) else item
            if isinstance(m, str):
                ms = m.strip()
                if ms and len(ms) <= 120 and ms not in seen:
                    seen.append(ms)
        if seen:
            p['available_models'] = seen

    raw_price = raw.get('price_per_second')
    if raw_price not in (None, ''):
        if isinstance(raw_price, bool):
            raise ValueError('每秒单价须为数字。')
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            raise ValueError('每秒单价须为有效数字。') from None
        if not math.isfinite(price) or not 0 <= price <= 1000:
            raise ValueError('每秒单价须在 0–1000 之间。')
        if price > 0:
            p['price_per_second'] = round(price, 4)
    return p


class UpstreamError(RuntimeError):
    def __init__(self, status, detail=''):
        self.status = status
        super().__init__(f'上游返回 HTTP {status}' + ('：'+detail if detail else ''))


def validate_submission(profile, item):
    """Reject incompatible tiers before any upload or paid POST; never round silently."""
    if profile['protocol'] == 'openai-video-v1':
        if not item.get('prompt') or len(item['prompt']) > 20000:
            raise ValueError('通用接口提示词须为 1—20000 字符。')
        if item['width'] * 9 != item['height'] * 16:
            raise ValueError('当前作品画幅须为 16:9。')
        if not item.get('bindings'):
            raise ValueError('当前镜头缺少参考图绑定，未提交。')
        return
    if item.get('required_protocol') and item['required_protocol'] != profile['protocol']:
        raise ValueError('本镜已按指定接口档位编写，请选择对应协议，或先重新适配。')
    if profile['protocol'] == 'doubao-canvas-v1':
        if item.get('requested_model') != 'seedance2' or item['model_request_seconds'] != 15:
            raise ValueError('本豆包画布分支只接受已适配的Seedance 2.0中文15秒稿。')
        if item['width'] * 9 != item['height'] * 16:
            raise ValueError('本剧豆包画布稿须为16:9。')
        if not item.get('prompt') or len(item['prompt']) > 20000 or not 1 <= len(item.get('bindings', [])) <= 9:
            raise ValueError('豆包画布提示词须为1—20000字符，参考图片为1—9张。')
        if any(b.get('role', 'reference_image') != 'reference_image' for b in item['bindings']):
            raise ValueError('本次豆包画布适配仅上传已确认图片。')
        return
    if profile['protocol'] == 'wan-portal-v1':
        expected = {'480P': (854,480), '720P': (1280,720), '1080P': (1920,1080)}[profile.get('video_resolution','1080P')]
        if (item.get('requested_model') != 'wan3' or item['model_request_seconds'] != 30
                or (item['width'],item['height']) != expected):
            raise ValueError('本工作区Wan3主生成须为30秒、16:9及Wan3正文。')
        if len(item.get('prompt', '')) > 20000 or not 1 <= len(item.get('bindings', [])) <= 10:
            raise ValueError('Wan3提示词须不超过20000字符，图片为1—10张。')
        if any(b.get('role', 'reference_image') != 'reference_image' for b in item['bindings']):
            raise ValueError('当前Wan3工作区适配仅允许图片参考。')
        return
    if profile['protocol'] == 'scenora-v1':
        model = profile['preset_map'][item['preset']]
        resolution = profile.get('video_resolution', '1080p').lower()
        prompt = item.get('prompt', '')
        bindings = item.get('bindings', [])
        if not prompt or len(prompt) > 5000:
            raise ValueError('映流 Scenora 提示词须为 1—5000 字符。')
        if item['width'] * 9 != item['height'] * 16:
            raise ValueError('当前作品画幅须为 16:9。')
        if model == 'wan3-pro':
            if (item.get('requested_model') != 'wan3' or item['model_request_seconds'] != 30
                    or resolution != '1080p' or (item['width'], item['height']) != (1920, 1080)):
                raise ValueError('映流 wan3-pro 仅支持 30 秒、1080p、16:9 及 Wan3 正文。')
        elif model == 'wan3':
            max_s = 30 if resolution == '720p' else 15
            expected_res = {'720p': (1280, 720), '1080p': (1920, 1080)}.get(resolution)
            if (item.get('requested_model') != 'wan3' or resolution not in ('720p', '1080p')
                    or not 4 <= item['model_request_seconds'] <= max_s
                    or (item['width'], item['height']) != expected_res):
                raise ValueError(f'映流 wan3 在 {resolution} 下仅支持 4—{max_s} 秒及对应 16:9 画幅。')
        elif model in ('seedance-2.0-full', 'seedance-2.0-face'):
            expected_res = {'480p': (854, 480), '720p': (1280, 720)}.get(resolution)
            if (item.get('requested_model') != 'seedance2' or resolution not in ('480p', '720p')
                    or not 4 <= item['model_request_seconds'] <= 15
                    or (item['width'], item['height']) != expected_res):
                raise ValueError(f'映流 {model} 仅支持 480p/720p 与 4—15 秒。')
        else:
            raise ValueError(f'映流 Scenora 尚不支持模型：{model}')
        if model in ('wan3', 'wan3-pro'):
            if not 1 <= len(bindings) <= 9 or any(b.get('role', 'reference_image') != 'reference_image' for b in bindings):
                raise ValueError('映流 Wan3 当前支持 1—9 张图片参考，不支持视频或音频参考。')
        elif model in ('seedance-2.0-full', 'seedance-2.0-face'):
            img_count = sum(b.get('role', 'reference_image') == 'reference_image' for b in bindings)
            vid_count = sum(b.get('role') == 'reference_video' for b in bindings)
            if not bindings or img_count > 9 or vid_count > 3 or img_count + vid_count != len(bindings):
                raise ValueError('映流 Seedance 2.0 当前支持 1—9 张图片或最多 3 个视频参考。')
        return
    if profile['protocol'] != 'rb-v1' or urlsplit(profile['base_url']).hostname != 'rb.coolhs.com':
        return
    preset = profile['preset_map'][item['preset']]
    tiers = {'reference': ((4, 6, 8), None, 8),
             'easy_15': ((15,), (1344, 768), 7),
             'dmad_20': ((20,), (1184, 672), 9),
             'dmad_30': ((30,), (1184, 672), 9)}
    if preset not in tiers:
        raise ValueError('当前RB预设尚未核对，请先核对档位后再提交。')
    durations, canvas, max_images = tiers[preset]
    if item['model_request_seconds'] not in durations:
        raise ValueError(f'RB {preset} 只支持 {"、".join(map(str,durations))} 秒，未提交。')
    if canvas and (item['width'], item['height']) != canvas:
        raise ValueError(f'RB {preset} 固定画幅为 {canvas[0]}×{canvas[1]}，未提交。')
    if len(item.get('bindings', [])) > max_images:
        raise ValueError(f'RB {preset} 本次核实的参考图上限为 {max_images} 张。')
    if preset.startswith('dmad_') and len(item['prompt'].split('\n------\n')) != 2:
        raise ValueError('RB拼接档须包含两个完整分段，未提交。')


class RBClient:
    def __init__(self, profile, key):
        self.profile = validate_profile(profile)
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer ' + key
        self.images = {}

    def close(self):
        self.session.close()
        self.session.headers.pop('Authorization', None)

    def api(self, method, path, **kwargs):
        r = self.session.request(method, self.profile['base_url'] + path, timeout=(15, 60), allow_redirects=False, **kwargs)
        try:
            if not r.ok or r.is_redirect:
                raise UpstreamError(r.status_code)
            return r.json()
        finally:
            r.close()

    def jobs(self):
        found = {}; offset = 0
        while True:
            sep = '&' if '?' in self.profile['jobs_path'] else '?'
            page = self.api('GET', self.profile['jobs_path'] + f'{sep}limit=100&offset={offset}')
            jobs = page.get('jobs', [])
            for job in jobs:
                found[str(job['id'])] = job
            offset += len(jobs)
            if not jobs or offset >= page.get('total', offset):
                return found
            if offset > 100000:
                raise ValueError('任务列表分页异常。')

    def detail(self, jid):
        from urllib.parse import quote
        return self.api('GET', self.profile['jobs_path'].rstrip('/') + '/' + quote(str(jid), safe=''))['job']

    def upload(self, path, digest):
        if digest in self.images:
            return self.images[digest]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('参考图已变化，请由 agent 更新制作数据。')
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[path.suffix.lower()]
        name = digest[:24] + path.suffix.lower()
        signed = self.api('POST', self.profile['presign_path'], json={'name': name, 'size': len(data), 'mime': mime, 'kind': 'image'})
        if urlsplit(signed['url']).scheme != 'https':
            raise ValueError('上游返回了非 HTTPS 上传地址。')
        with requests.put(signed['url'], data=data, headers={'Content-Type': signed.get('contentType', mime)}, timeout=(15, 120), allow_redirects=False) as response:
            if not response.ok or response.is_redirect:
                raise UpstreamError(response.status_code)
        result = self.api('POST', self.profile['commit_path'], json={'key': signed['key'], 'name': name, 'kind': 'image'})['item']['ref']
        self.images[digest] = result
        return result

    def payload(self, item, refs):
        validate_submission(self.profile, item)
        if any(b.get('role', 'reference_image') != 'reference_image' for b in item.get('bindings', [])):
            raise ValueError('该接口尚未实现视频参考，请选择支持全能视频参考的接口。')
        return {'preset': self.profile['preset_map'][item['preset']], 'prompt': item['prompt'], 'images': refs,
                'width': item['width'], 'height': item['height'], 'seconds': item['model_request_seconds']}

    def submit(self, payload):
        job = self.api('POST', self.profile['jobs_path'], json=payload)['job']
        if not job.get('id'):
            raise ValueError('提交响应缺少任务编号。')
        return job

    def download(self, jid, output):
        from urllib.parse import quote
        path = self.profile['video_path'].replace('{id}', quote(str(jid), safe=''))
        response = self.session.get(self.profile['base_url'] + path, timeout=(15,20), stream=True, allow_redirects=False)
        if response.is_redirect:
            target = urljoin(self.profile['base_url'], response.headers['Location'])
            response.close()
            if urlsplit(target).scheme != 'https':
                raise ValueError('拒绝非 HTTPS 视频下载。')
            response = requests.get(target, stream=True, timeout=(15,20))
        part = output.with_suffix('.mp4.part'); output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(); size = 0; deadline = time.monotonic()+180
        try:
            response.raise_for_status()
            with part.open('wb') as f:
                for chunk in response.iter_content(1024*1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError('下载超时')
                    if chunk:
                        f.write(chunk); digest.update(chunk); size += len(chunk)
            with part.open('rb') as f:
                if size < 1024 or b'ftyp' not in f.read(16):
                    raise ValueError('下载结果不是有效 MP4。')
            part.replace(output)
            return {'size': size, 'sha256': digest.hexdigest()}
        finally:
            response.close()


def matches(item, job, profile):
    if profile.get('protocol') == 'wan-portal-v1':
        size_matches = job.get('resolution') == profile.get('video_resolution', '1080P') and job.get('aspect_ratio') == '16:9'
    elif profile.get('protocol') == 'scenora-v1':
        size_matches = job.get('resolution') == profile.get('video_resolution', '1080p').lower() and job.get('aspect_ratio') == '16:9'
    elif profile.get('protocol') == 'sparkcine-v1':
        size_matches = (job.get('resolution') == profile.get('video_resolution', '720p')
                        and job.get('aspect_ratio') == '16:9')
    else:
        size_matches = str(job.get('width')) == str(item['width']) and str(job.get('height')) == str(item['height'])
    return (str(job.get('preset')) == profile['preset_map'][item['preset']]
            and str(job.get('seconds')) == str(item['model_request_seconds']) and size_matches
            and str(job.get('prompt', '')).replace('\r\n', '\n').strip() == item['prompt'].replace('\r\n', '\n').strip())


def client_type(profile):
    if profile['protocol'] == 'doubao-canvas-v1':
        from doubao_canvas import DoubaoCanvasClient
        return DoubaoCanvasClient
    return {'rb-v1': RBClient, 'sparkcine-v1': SparkCineClient, 'wan-portal-v1': WanPortalClient, 'scenora-v1': ScenoraClient, 'openai-video-v1': OpenAIVideoClient}[profile['protocol']]


class WanPortalClient(RBClient):
    """wan.coolhs.com buyer API; native files, stable job ID, original full prompt."""

    def __init__(self, profile, key):
        super().__init__(profile, key)
        self.session.headers.pop('Authorization', None)
        self.session.headers.update({'X-Wan-Card': key, 'User-Agent': 'Mozilla/5.0'})

    def close(self):
        self.session.headers.pop('X-Wan-Card', None)
        super().close()

    def api(self, method, path, **kwargs):
        response = self.session.request(method, self.profile['base_url']+path, timeout=(15,90), allow_redirects=False, **kwargs)
        try:
            if not response.ok or response.is_redirect:
                detail = ''
                try:
                    body = response.json(); value = body.get('detail') or (body.get('error') or {}).get('message')
                    if isinstance(value,str): detail=value
                except (ValueError,TypeError,AttributeError): pass
                card = self.session.headers.get('X-Wan-Card','')
                if card: detail=detail.replace(card,'[redacted]')
                detail=re.sub(r'WAN-[A-Z0-9-]+','[redacted]',detail)[:700]
                raise UpstreamError(response.status_code,detail)
            return response.json()
        finally:
            response.close()

    @staticmethod
    def job_id(request_id):
        import uuid
        return uuid.uuid5(uuid.NAMESPACE_URL, 'studio-wan:' + request_id).hex

    @staticmethod
    def normalize(job):
        wait = job.get('wait') or {}
        raw = str(job.get('status', ''))
        phase = wait.get('phase')
        status = {'boarding': 'pending', 'queued': 'pending', 'running': 'running', 'done': 'done',
                  'failed': 'failed', 'cancelled': 'cancelled'}.get(phase)
        if status is None:
            status = {'boarded': 'pending', 'pending': 'pending', 'running': 'running',
                      'succeeded': 'done', 'completed': 'done', 'failed': 'failed', 'cancelled': 'cancelled'}.get(raw, raw)
        error = job.get('error') or wait.get('detail') if status == 'failed' else None
        error = re.sub(r'WAN-[A-Z0-9-]+', '[redacted]', str(error))[:700] if error else None
        return {'id': str(job['id']), 'status': status, 'provider_status': raw,
                'has_video': status == 'done', 'progress': job.get('progress'),
                'created_at': job.get('createdAt'), 'updated_at': job.get('updatedAt'),
                'preset': 'wan3', 'seconds': job.get('duration'), 'resolution': job.get('resolution'),
                'aspect_ratio': job.get('ratio'), 'prompt': job.get('prompt', ''),
                'wait_phase': phase, 'wait_label': str(wait.get('label') or ''),
                'queue_ahead': wait.get('ahead'), 'eta_depart_at': wait.get('etaDepartAt'),
                'error_message': error, 'error_code': None}

    def jobs(self):
        found, before = {}, None
        for _ in range(100):
            params = {'limit': 100}
            if before is not None: params['before'] = before
            page = self.api('GET', self.profile['jobs_path'], params=params)
            for raw in page.get('items', []):
                job = self.normalize(raw); found[job['id']] = job
            cursor = page.get('next')
            if cursor is None: return found
            if cursor == before: raise ValueError('Wan任务列表游标未前进。')
            before = cursor
        raise ValueError('Wan任务列表分页超限。')

    def detail(self, jid):
        from urllib.parse import quote
        raw = self.api('GET', self.profile['jobs_path'].rstrip('/') + '/' + quote(str(jid), safe=''))
        return self.normalize(raw)

    def upload(self, path, digest):
        if digest in self.images: return self.images[digest]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('参考图已变化，未上传。')
        from PIL import Image
        with Image.open(path) as im:
            if max(im.size) > 8000 or max(im.size) / min(im.size) > 8 or min(im.size) < 240:
                raise ValueError('参考图超出Wan规格；未缩放或改图。')
        if len(data) > 20 * 1024 * 1024: raise ValueError('参考图超过20MB。')
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[path.suffix.lower()]
        name = digest[:24] + path.suffix.lower()
        signed = self.api('POST', self.profile['presign_path'], json={'name': name, 'kind': 'image', 'size': len(data), 'mime': mime})
        if urlsplit(signed['url']).scheme != 'https': raise ValueError('上传地址须为HTTPS。')
        # Object storage receives only its signed URL and Content-Type, never the card.
        with requests.put(signed['url'], data=data, headers={'Content-Type': signed.get('contentType', mime)}, timeout=(15, 180), allow_redirects=False) as response:
            if not response.ok or response.is_redirect: raise UpstreamError(response.status_code)
        result = self.api('POST', self.profile['commit_path'], json={'key': signed['key'], 'name': name, 'kind': 'image', 'mime': mime})
        media_id = str(result.get('id') or '')
        if not media_id: raise ValueError('上传登记缺少素材ID。')
        self.images[digest] = media_id
        return media_id

    def payload(self, item, refs, request_id):
        validate_submission(self.profile, item)
        if len(refs) != len(item['bindings']): raise ValueError('图片数与冻结图序不一致。')
        return {'id': self.job_id(request_id), 'prompt': item['prompt'], 'ratio': '16:9',
                'resolution': self.profile.get('video_resolution', '1080P'), 'duration': 30,
                'audio': True, 'copies': 1, 'promptExtend': 0,
                'media': [{'id': ref, 'kind': 'image', 'token': f'图{i}', 'role': 'ref'} for i, ref in enumerate(refs, 1)]}

    def submit(self, payload):
        account = self.api('GET', '/api/portal/me')
        ride = self.api('GET', '/api/portal/ride')
        if account.get('blocked') or account.get('remaining', 0) <= 0:
            raise ValueError('Wan卡密额度不足或已停止接单。')
        if not ride.get('accepting'):
            raise UpstreamError(503)
        result = self.api('POST', self.profile['jobs_path'], json=payload)
        job = result.get('job') or {}
        if str(job.get('id')) != payload['id']: raise ValueError('提交返回的任务ID与固定ID不一致，需核对。')
        return self.normalize(job)

    def cancel(self, jid):
        from urllib.parse import quote
        result=self.api('DELETE',self.profile['jobs_path'].rstrip('/')+'/'+quote(str(jid),safe=''))
        job=self.normalize(result['job'])
        if job['status']!='cancelled':raise ValueError('上游未确认取消，未改写本地状态。')
        return job,result.get('remaining')


class SparkCineClient(RBClient):
    """SparkCine native API: original prompt, uploaded references, stable idempotency key."""

    def jobs(self):
        found = {}; cursor = None
        for _ in range(1000):
            params = {'limit': 100}
            if cursor:
                params['cursor'] = cursor
            page = self.api('GET', self.profile['jobs_path'], params=params)
            for job in page.get('data', []):
                normalized = self.normalize(job)
                found[str(normalized['id'])] = normalized
            if not page.get('has_more'):
                return found
            next_cursor = page.get('next_cursor')
            if not next_cursor or next_cursor == cursor:
                raise ValueError('SparkCine 任务列表分页异常。')
            cursor = next_cursor
        raise ValueError('SparkCine 任务列表超过安全分页上限。')

    @staticmethod
    def normalize(job):
        status = str(job.get('status', ''))
        mapped = {'queued': 'pending', 'confirming': 'pending', 'delayed': 'pending',
                  'generating': 'running', 'finalizing': 'running', 'cancelling': 'running',
                  'succeeded': 'done', 'failed': 'failed', 'cancelled': 'cancelled'}.get(status, status)
        parameters = job.get('parameters') or {}
        size = {'480p': (854,480), '720p': (1280,720), '768p': (1366,768),
                '960p': (1706,960), '1080p': (1920,1080)}.get(parameters.get('resolution'), (None,None))
        outputs = job.get('outputs') or []
        return {'id': str(job['id']), 'status': mapped, 'provider_status': status,
                'has_video': bool(job.get('output_asset_ids') or outputs),
                'error_code': (job.get('error') or {}).get('code'),
                'created_at': job.get('created_at'), 'updated_at': job.get('updated_at'),
                'preset': job.get('model'), 'seconds': parameters.get('duration'),
                'resolution': parameters.get('resolution'), 'aspect_ratio': parameters.get('aspect_ratio'),
                'width': size[0], 'height': size[1], 'prompt': job.get('prompt', ''),
                'outputs': outputs, 'metadata': job.get('metadata') or {}}

    def detail(self, jid):
        from urllib.parse import quote
        return self.normalize(self.api('GET', self.profile['jobs_path'].rstrip('/')+'/'+quote(str(jid),safe='')))

    def upload(self, path, digest):
        from urllib.parse import quote
        if digest in self.images:
            return self.images[digest]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('参考图已变化，请重新核对。')
        mime = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.webp':'image/webp',
                '.mp4':'video/mp4'}[path.suffix.lower()]
        uploaded = self.api('POST', self.profile['presign_path'], json={
            'filename': digest[:24]+path.suffix.lower(), 'content_type': mime,
            'byte_length': len(data), 'sha256': digest})
        asset_id = str(uploaded['asset_id'])
        if not (uploaded.get('reused') is True and uploaded.get('state') == 'READY'):
            upload = uploaded['upload']; target = urljoin(self.profile['base_url']+'/', upload['url'])
            if urlsplit(target).scheme != 'https' or upload.get('method','PUT').upper() != 'PUT':
                raise ValueError('上传地址或方法无效。')
            # The signed upload has its own headers: never forward the API key to storage.
            with requests.put(target, data=data, headers=upload.get('headers') or {}, timeout=(15,120), allow_redirects=False) as response:
                if not response.ok or response.is_redirect:
                    raise UpstreamError(response.status_code)
            complete_path = self.profile['commit_path'].replace('{id}', quote(asset_id,safe=''))
            self.api('POST', complete_path, json={})
        self.images[digest] = asset_id
        return asset_id

    def payload(self, item, refs, request_id):
        if item['width']*9 != item['height']*16 or not 4 <= item['model_request_seconds'] <= 15:
            raise ValueError('SparkCine 当前支持 16:9、4–15 秒配置。')
        bindings = item.get('bindings')
        if bindings is not None and len(bindings) != len(refs):
            raise ValueError('参考素材与冻结绑定数量不一致。')
        roles = [b.get('role', 'reference_image') for b in bindings] if bindings is not None else ['reference_image']*len(refs)
        if any(role not in ('reference_image', 'reference_video') for role in roles):
            raise ValueError('不支持的参考素材用途。')
        parameters = {'duration':item['model_request_seconds'], 'resolution':self.profile.get('video_resolution','720p'),
                      'aspect_ratio':'16:9', 'generate_audio':True}
        if 'mute_reference_video' in item:
            if not isinstance(item['mute_reference_video'], bool):
                raise ValueError('mute_reference_video 必须为布尔值。')
            parameters['mute_reference_video'] = item['mute_reference_video']
        return {'model':self.profile['preset_map'][item['preset']], 'prompt':item['prompt'],
                'inputs':[{'asset_id':ref,'role':role} for ref,role in zip(refs,roles)],
                'parameters':parameters,
                'optimize_prompt':False, 'metadata':{'studio_request_id':request_id},
                'note':item['unit_id'][:80]}

    def submit(self, payload):
        request_id = payload['metadata']['studio_request_id']
        key = 'studio-'+hashlib.sha256(request_id.encode()).hexdigest()
        job = self.api('POST', self.profile['jobs_path'], json=payload, headers={'Idempotency-Key':key})
        if not job.get('id'):
            raise ValueError('提交响应缺少任务编号。')
        return self.normalize(job)

    def download(self, jid, output):
        job = self.detail(jid)
        video = next((o for o in job['outputs'] if o.get('media_type')=='video' or
                      str(o.get('mime_type','')).startswith('video/')), None)
        if not video or not video.get('download_url'):
            raise ValueError('任务尚无可下载的视频。')
        target = video['download_url']
        if urlsplit(target).scheme != 'https':
            raise ValueError('拒绝非 HTTPS 视频下载。')
        part = output.with_suffix('.mp4.part'); output.parent.mkdir(parents=True,exist_ok=True)
        digest = hashlib.sha256(); size = 0; deadline = time.monotonic()+180
        # Signed download URLs have their own authorization, not the API key.
        with requests.get(target, stream=True, timeout=(15,20), allow_redirects=False) as response:
            if not response.ok or response.is_redirect:
                raise UpstreamError(response.status_code)
            with part.open('wb') as f:
                for chunk in response.iter_content(1024*1024):
                    if time.monotonic()>deadline:raise TimeoutError('下载超时')
                    if chunk:f.write(chunk);digest.update(chunk);size+=len(chunk)
        with part.open('rb') as f:
            if size<1024 or b'ftyp' not in f.read(16):raise ValueError('下载结果不是有效 MP4。')
        if video.get('byte_length') is not None and size != int(video['byte_length']):
            raise ValueError('视频下载字节数不一致。')
        part.replace(output)
        return {'size':size,'sha256':digest.hexdigest()}


class ScenoraClient(RBClient):
    """scenora.ink OpenAPI v1: service/model capability & quote check, /v1/assets base64, idempotent submit."""

    def __init__(self, profile, key):
        super().__init__(profile, key)
        self._key = key
        self.session.headers['Accept'] = 'application/json'

    def _redact(self, text):
        cleaned = str(text or '')
        if self._key:
            cleaned = cleaned.replace(self._key, '[redacted]')
        return re.sub(r'sk[-_][A-Za-z0-9_-]+', '[redacted]', cleaned)[:700]

    def api(self, method, path, **kwargs):
        r = self.session.request(method, api_join(self.profile['base_url'], path), timeout=(15, 90), allow_redirects=False, **kwargs)
        try:
            if not r.ok or r.is_redirect:
                detail = ''
                try:
                    body = r.json()
                    value = (body.get('error') or {}).get('message') if isinstance(body.get('error'), dict) else body.get('detail')
                    if isinstance(value, str):
                        detail = self._redact(value)
                except (ValueError, TypeError, AttributeError):
                    pass
                raise UpstreamError(r.status_code, detail)
            return r.json()
        finally:
            r.close()

    @staticmethod
    def normalize(task):
        raw = str(task.get('status', ''))
        status = {'queued': 'pending', 'submitting': 'pending', 'running': 'running',
                  'needs_review': 'running', 'completed': 'done', 'failed': 'failed',
                  'canceled': 'cancelled'}.get(raw, raw)
        res = str(task.get('resolution') or '').lower()
        size = {'480p': (854, 480), '720p': (1280, 720), '1080p': (1920, 1080)}.get(res, (None, None))
        err = task.get('error') or None
        return {'id': str(task['id']), 'status': status, 'provider_status': raw,
                'has_video': raw == 'completed', 'error_code': None, 'error_message': err,
                'created_at': task.get('created_at'),
                'updated_at': task.get('finished_at') or task.get('started_at') or task.get('created_at'),
                'preset': task.get('model'), 'seconds': task.get('duration'),
                'resolution': res or None, 'aspect_ratio': task.get('ratio'),
                'width': size[0], 'height': size[1], 'prompt': task.get('prompt', ''),
                'client_reference': task.get('client_reference'),
                'billing': task.get('billing'), 'price_units': task.get('price_units')}

    def jobs(self):
        found, offset = {}, 0
        for _ in range(500):
            page = self.api('GET', '/v1/videos', params={'limit': 200, 'offset': offset})
            tasks = page.get('tasks', [])
            for raw in tasks:
                job = self.normalize(raw)
                found[job['id']] = job
            offset += len(tasks)
            if not tasks or offset >= int(page.get('total', offset)):
                return found
        raise ValueError('映流 Scenora 任务列表超过安全分页上限。')

    def detail(self, jid):
        from urllib.parse import quote
        raw = self.api('GET', '/v1/videos/' + quote(str(jid), safe=''))
        return self.normalize(raw)

    def upload(self, path, digest):
        if digest in self.images:
            return self.images[digest]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('参考图已变化，未上传。')
        suffix = path.suffix.lower()
        if suffix not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('映流 Wan3 参考图仅支持 PNG、JPG、JPEG 或 WebP。')
        if len(data) > 10 * 1024 * 1024:
            raise ValueError('参考图超过映流 10 MB 单张上限。')
        from PIL import Image
        with Image.open(path) as im:
            if max(im.size) > 16384 or min(im.size) < 1:
                raise ValueError('参考图尺寸超出映流 16384 像素限制。')
        result = self.api('POST', self.profile['presign_path'],
                          json={'name': digest[:24] + suffix, 'base64': base64.b64encode(data).decode('ascii')})
        asset_id = str((result.get('asset') or {}).get('id') or '')
        if not asset_id:
            raise ValueError('映流上传响应缺少素材编号。')
        self.images[digest] = asset_id
        return asset_id

    def payload(self, item, refs, request_id):
        validate_submission(self.profile, item)
        if len(refs) != len(item.get('bindings', [])):
            raise ValueError('图片数与冻结图序不一致。')
        model = self.profile['preset_map'][item['preset']]
        resolution = self.profile.get('video_resolution', '1080p').lower()
        duration = int(item['model_request_seconds'])
        quote = self.api('POST', '/v1/videos/quote',
                         json={'model': model, 'duration': duration, 'resolution': resolution, 'ratio': '16:9'})
        price_units = int(quote['price_units'])
        limit = self.profile.get('max_price_units')
        if limit is not None and price_units > limit:
            raise UpstreamError(409, '实时价格超过本次授权上限，未发送视频生成请求。')
        if quote.get('sufficient') is False:
            raise ValueError('映流 Scenora 账户可用积分不足，未提交生成。')
        client_ref = ('studio-' + hashlib.sha256(request_id.encode()).hexdigest())[:64]
        return {'model': model, 'prompt': item['prompt'], 'duration': duration,
                'resolution': resolution, 'ratio': '16:9',
                'expected_price_units': price_units,
                'expected_pricing_revision': str(quote['pricing_revision']),
                'client_reference': client_ref, 'reference_asset_ids': list(refs)}

    def submit(self, payload):
        status = self.api('GET', '/v1/service-status')
        model_info = (status.get('models') or {}).get(payload['model']) or {}
        if not status.get('enabled') or not model_info.get('enabled', True):
            reason = self._redact(model_info.get('reason') or status.get('reason') or '生成服务暂未开放')
            raise UpstreamError(503, reason)
        balance = self.api('GET', '/v1/balance')
        if int(balance.get('available_units', 0)) < int(payload['expected_price_units']):
            raise ValueError('映流 Scenora 账户可用积分不足，未提交生成。')
        task = self.api('POST', self.profile['jobs_path'], json=payload,
                        headers={'Idempotency-Key': payload['client_reference']})
        if not task.get('id'):
            raise ValueError('提交响应缺少任务编号。')
        return self.normalize(task)

    def download(self, jid, output):
        job = self.detail(jid)
        if job.get('status') != 'done':
            raise ValueError('任务尚无可下载的视频。')
        return super().download(jid, output)


def _extract_model_entries(body):
    raw_items = []
    if isinstance(body, dict):
        if isinstance(body.get('data'), list):
            raw_items = body['data']
        elif isinstance(body.get('models'), list):
            raw_items = body['models']
        elif isinstance(body.get('models'), dict):
            raw_items = [{'id': k, **(v if isinstance(v, dict) else {})} for k, v in body['models'].items()]
        elif isinstance(body.get('items'), list):
            raw_items = body['items']
    elif isinstance(body, list):
        raw_items = body
    seen, entries = set(), []
    for item in raw_items:
        if isinstance(item, str):
            mid, enabled, note = item.strip(), True, ''
        elif isinstance(item, dict):
            mid = str(item.get('id') or item.get('model') or item.get('name') or '').strip()
            enabled = bool(item.get('enabled', True))
            note = str(item.get('reason') or item.get('owned_by') or '').strip()
        else:
            continue
        if not mid or mid in seen or len(mid) > 120:
            continue
        seen.add(mid)
        label = mid + (f'（{note}）' if note and note != mid else '')
        entries.append({'id': mid, 'label': label, 'enabled': enabled, 'is_video': any(h in mid.lower() for h in VIDEO_MODEL_HINTS)})
    entries.sort(key=lambda e: (0 if e['enabled'] else 1, 0 if e['is_video'] else 1, e['id'].lower()))
    return [{'id': e['id'], 'label': e['label'], 'enabled': e['enabled']} for e in entries]


class OpenAIVideoClient(RBClient):
    """Generic OpenAI-compatible / relay video API (/v1/models, /v1/videos)."""

    def __init__(self, profile, key):
        super().__init__(profile, key)
        self._key = key
        self.session.headers['Accept'] = 'application/json'

    def _redact(self, text):
        cleaned = str(text or '')
        if self._key:
            cleaned = cleaned.replace(self._key, '[redacted]')
        cleaned = re.sub(r'sk[-_][A-Za-z0-9_-]+', '[redacted]', cleaned)
        return re.sub(r'WAN-[A-Z0-9-]+', '[redacted]', cleaned)[:700]

    def api(self, method, path, **kwargs):
        url = path if path.startswith(('https://', 'http://')) else api_join(self.profile['base_url'], path)
        r = self.session.request(method, url, timeout=(15, 90), allow_redirects=False, **kwargs)
        try:
            if not r.ok or r.is_redirect:
                detail = ''
                try:
                    body = r.json()
                    value = (body.get('error') or {}).get('message') if isinstance(body.get('error'), dict) else body.get('detail') or body.get('message')
                    if isinstance(value, str):
                        detail = self._redact(value)
                except (ValueError, TypeError, AttributeError):
                    pass
                raise UpstreamError(r.status_code, detail)
            return r.json()
        finally:
            r.close()

    def models(self):
        last_err = None
        for path in ('/v1/models', '/models'):
            try:
                body = self.api('GET', path)
                items = _extract_model_entries(body)
                if items:
                    return items
            except UpstreamError as err:
                last_err = err
                if err.status in (401, 403):
                    raise
                if err.status not in (404, 405):
                    raise
            except (ValueError, TypeError) as err:
                last_err = err
        if isinstance(last_err, UpstreamError):
            raise last_err
        raise ValueError('上游未返回可用的模型列表，请检查接口地址或手动输入模型名。')

    @staticmethod
    def normalize(task):
        raw = str(task.get('status') or '')
        low = raw.lower()
        status = {
            'queued': 'pending', 'pending': 'pending', 'submitted': 'pending', 'submitting': 'pending',
            'in_progress': 'running', 'processing': 'running', 'running': 'running', 'generating': 'running',
            'completed': 'done', 'succeeded': 'done', 'success': 'done', 'done': 'done',
            'failed': 'failed', 'error': 'failed', 'cancelled': 'cancelled', 'canceled': 'cancelled',
        }.get(low, raw)
        err = task.get('error')
        if isinstance(err, dict):
            err = err.get('message') or err.get('code') or str(err)
        video_url = (
            task.get('video_url')
            or task.get('url')
            or (task.get('output') or {}).get('url')
            or next((o.get('url') or o.get('download_url') for o in (task.get('outputs') or []) if isinstance(o, dict) and (o.get('url') or o.get('download_url'))), '')
            or ((task.get('assets') or {}).get('video') if isinstance(task.get('assets'), dict) else '')
        )
        return {
            'id': str(task.get('id') or task.get('task_id') or ''),
            'status': status,
            'provider_status': raw,
            'has_video': bool(video_url or status == 'done'),
            'video_url': str(video_url or ''),
            'error_code': None,
            'error_message': str(err) if err else None,
            'created_at': task.get('created_at'),
            'updated_at': task.get('finished_at') or task.get('updated_at') or task.get('created_at'),
            'preset': task.get('model'),
            'seconds': task.get('seconds') or task.get('duration'),
            'resolution': task.get('resolution') or task.get('size'),
            'aspect_ratio': task.get('ratio') or task.get('aspect_ratio') or '16:9',
            'prompt': task.get('prompt', ''),
        }

    def jobs(self):
        try:
            page = self.api('GET', self.profile['jobs_path'])
        except UpstreamError as err:
            if err.status in (404, 405):
                return {}
            raise
        raw_list = page.get('data') or page.get('tasks') or page.get('items') or page.get('jobs') or []
        found = {}
        if isinstance(raw_list, list):
            for raw in raw_list:
                if isinstance(raw, dict) and (raw.get('id') or raw.get('task_id')):
                    job = self.normalize(raw)
                    found[job['id']] = job
        return found

    def detail(self, jid):
        from urllib.parse import quote
        raw = self.api('GET', self.profile['jobs_path'].rstrip('/') + '/' + quote(str(jid), safe=''))
        if isinstance(raw, dict) and isinstance(raw.get('data'), dict) and 'id' not in raw:
            raw = raw['data']
        return self.normalize(raw)

    def upload(self, path, digest):
        if digest in self.images:
            return self.images[digest]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('参考图已变化，未上传。')
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(path.suffix.lower())
        if not mime:
            raise ValueError('通用接口参考图仅支持 PNG、JPG、JPEG 或 WebP。')
        uri = f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'
        self.images[digest] = uri
        return uri

    def payload(self, item, refs, request_id=None):
        validate_submission(self.profile, item)
        res = str(self.profile.get('video_resolution') or '1080p').lower()
        size = {'480p': '854x480', '720p': '1280x720', '768p': '1366x768', '1080p': '1920x1080'}.get(res, '1920x1080')
        model = self.profile.get('model') or self.profile['preset_map']['reference']
        body = {
            'model': model,
            'prompt': item['prompt'],
            'seconds': int(item['model_request_seconds']),
            'resolution': res,
            'size': size,
            'aspect_ratio': '16:9',
            'image_urls': list(refs),
        }
        if request_id:
            body['metadata'] = {'studio_request_id': request_id}
        return body

    def submit(self, payload):
        raw = self.api('POST', self.profile['jobs_path'], json=payload)
        if isinstance(raw, dict) and isinstance(raw.get('data'), dict) and 'id' not in raw and 'task_id' not in raw:
            raw = raw['data']
        if isinstance(raw, dict) and isinstance(raw.get('job'), dict):
            raw = raw['job']
        job = self.normalize(raw)
        if not job.get('id'):
            raise ValueError('提交响应缺少任务编号。')
        return job

    def download(self, jid, output):
        from urllib.parse import quote
        job = self.detail(jid)
        target = job.get('video_url')
        if not target:
            target = api_join(self.profile['base_url'], self.profile['video_path'].replace('{id}', quote(str(jid), safe='')))
            response = self.session.get(target, timeout=(15, 20), stream=True, allow_redirects=False)
            if response.is_redirect:
                target = urljoin(self.profile['base_url'], response.headers['Location'])
                response.close()
                u = urlsplit(target)
                if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost')):
                    raise ValueError('拒绝非 HTTPS 视频下载。')
                response = requests.get(target, stream=True, timeout=(15, 20))
        else:
            u = urlsplit(target)
            if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost')):
                raise ValueError('拒绝非 HTTPS 视频下载。')
            same_host = target.startswith(self.profile['base_url'])
            response = (self.session if same_host else requests).get(target, stream=True, timeout=(15, 20))
        part = output.with_suffix('.mp4.part')
        output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(); size = 0; deadline = time.monotonic() + 180
        try:
            response.raise_for_status()
            with part.open('wb') as f:
                for chunk in response.iter_content(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise TimeoutError('下载超时')
                    if chunk:
                        f.write(chunk); digest.update(chunk); size += len(chunk)
            with part.open('rb') as f:
                if size < 1024 or b'ftyp' not in f.read(16):
                    raise ValueError('下载结果不是有效 MP4。')
            part.replace(output)
            return {'size': size, 'sha256': digest.hexdigest()}
        finally:
            response.close()


def fetch_upstream_models(profile_data, key):
    raw = dict(profile_data or {})
    raw.setdefault('id', 'probe-models')
    raw.setdefault('name', '临时查询')
    if not str(raw.get('model') or '').strip() and not isinstance(raw.get('preset_map'), dict):
        raw['model'] = 'reference'
    profile = validate_profile(raw)
    if not key:
        raise ValueError('请先输入该接口的密钥，再向上游获取模型。')
    proto = profile['protocol']
    if proto == 'openai-video-v1':
        client = OpenAIVideoClient(profile, key)
        try:
            return client.models()
        except UpstreamError as err:
            raise ValueError(f'接口返回 HTTP {err.status}，请检查接口地址与密钥。') from None
        except ValueError:
            raise
        except Exception:
            raise ValueError('暂时无法连接该接口获取模型，请检查网络或接口地址。') from None
        finally:
            client.close()
    if proto == 'scenora-v1':
        client = ScenoraClient(profile, key)
        try:
            models = []
            try:
                status = client.api('GET', '/v1/service-status')
                models = _extract_model_entries({'models': status.get('models') or {}})
            except UpstreamError as err:
                if err.status in (401, 403):
                    raise
            if not models:
                models = _extract_model_entries(client.api('GET', '/v1/models'))
            if not models:
                raise ValueError('映流 Scenora 未返回可用模型列表。')
            return models
        except UpstreamError as err:
            raise ValueError(f'接口返回 HTTP {err.status}，请检查密钥与地址。') from None
        except ValueError:
            raise
        except Exception:
            raise ValueError('暂时无法连接映流 Scenora 获取模型。') from None
        finally:
            client.close()
    if proto == 'sparkcine-v1':
        client = RBClient(profile, key)
        try:
            for path in ('/api/open/v1/models', '/v1/models'):
                try:
                    items = _extract_model_entries(client.api('GET', path))
                    if items:
                        return items
                except UpstreamError as err:
                    if err.status in (401, 403):
                        raise
            client.jobs()
            return [
                {'id': 'h3-video-flex', 'label': 'h3-video-flex', 'enabled': True},
                {'id': 'h3-video', 'label': 'h3-video', 'enabled': True},
            ]
        except UpstreamError as err:
            raise ValueError(f'接口返回 HTTP {err.status}，请检查密钥。') from None
        except Exception:
            raise ValueError('暂时无法连接 SparkCine 获取模型。') from None
        finally:
            client.close()
    if proto == 'wan-portal-v1':
        client = WanPortalClient(profile, key)
        try:
            client.api('GET', '/api/portal/me')
            return [{'id': 'wan3', 'label': 'wan3 · 万万工作台（1080P/30s）', 'enabled': True}]
        except UpstreamError as err:
            raise ValueError(f'接口返回 HTTP {err.status}，请检查 Wan 卡密。') from None
        except Exception:
            raise ValueError('暂时无法连接万万工作台。') from None
        finally:
            client.close()
    if proto == 'doubao-canvas-v1':
        from doubao_canvas import DoubaoCanvasClient
        client = DoubaoCanvasClient(profile, key)
        try:
            client.check()
            return [{'id': 'seedance2', 'label': 'seedance2 · Seedance 2.0', 'enabled': True}]
        except Exception:
            raise ValueError('无法验证豆包画布会话，请检查会话信息。') from None
        finally:
            client.close()
    client = RBClient(profile, key)
    try:
        try:
            items = _extract_model_entries(client.api('GET', '/api/v1/models'))
            if items:
                return items
        except UpstreamError as err:
            if err.status in (401, 403):
                raise
        client.jobs()
        return [
            {'id': 'reference', 'label': 'reference（短镜头 4/6/8s）', 'enabled': True},
            {'id': 'easy_15', 'label': 'easy_15（15秒标准）', 'enabled': True},
            {'id': 'dmad_20', 'label': 'dmad_20（20秒拼接）', 'enabled': True},
            {'id': 'dmad_30', 'label': 'dmad_30（30秒拼接）', 'enabled': True},
        ]
    except UpstreamError as err:
        raise ValueError(f'接口返回 HTTP {err.status}，请检查密钥与地址。') from None
    except Exception:
        raise ValueError('暂时无法连接上游获取模型。') from None
    finally:
        client.close()
