"""Doubao canvas protocol adapted from the user-supplied Qige 1.0.18 archive.
Uses one in-memory session. No guest rotation, fingerprint randomization,
quota bypass, plugin updater, host hooks or watermark decoding is loaded.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import threading
import time
import uuid
import zlib
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import quote, urlsplit
import requests
from PIL import Image
from upstream import RBClient, UpstreamError, validate_profile, validate_submission

BASE = "https://www.doubao.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36 Edg/156.0.0.0"
_RUNTIME = {}
_LOCK = threading.RLock()

def new_session_key():
    return "studio-single-session-" + uuid.uuid4().hex


def configure(session, proxy=""):
    session.trust_env = False
    session.proxies = {"http": proxy, "https": proxy} if proxy else {}
    return session


class ProtocolError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def signature(method, path, query, headers, body, token):
    """Sign the top/v1 gateway using the current short-lived upload credential."""
    headers = {k.lower(): str(v).strip() for k, v in headers.items()}
    signed = ";".join(sorted(headers))
    cq = "&".join(quote(str(k), safe="-_.~") + "=" + quote(str(v), safe="-_.~") for k, v in sorted(query.items()))
    canonical = "\n".join([method, path, cq, "".join(k + ":" + headers[k] + "\n" for k in sorted(headers)), signed, hashlib.sha256(body).hexdigest()])
    date = headers["x-amz-date"]
    scope = date[:8] + "/cn-north-1/imagex/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("AWS4" + token["secret_key"]).encode()
    for value in [date[:8], "cn-north-1", "imagex", "aws4_request"]:
        key = hmac.new(key, value.encode(), hashlib.sha256).digest()
    return "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (token["access_key"], scope, signed, hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest())


class CanvasTransport:
    def __init__(self, key):
        # A session key only indexes RAM; cookies and upload tokens never enter JSON.
        with _LOCK:
            state = _RUNTIME.get(key)
            if state is None:
                session = configure(requests.Session())
                session.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                    "Agw-Js-Conv": "str", "Origin": BASE, "Referer": BASE + "/chat/"})
                if not key.startswith("studio-single-session-"):
                    cookie = SimpleCookie()
                    try: cookie.load(key)
                    except Exception: raise ValueError("豆包会话格式无效") from None
                    if not (cookie.get("sessionid") or cookie.get("sessionid_ss")):
                        raise ValueError("请提供本人已登录豆包的会话，或显式初始化单一游客会话")
                    for name, value in cookie.items():
                        session.cookies.set(name, value.value, domain=".doubao.com", path="/")
                state = {"session": session, "warmed": False, "device": str(uuid.uuid4()),
                         "web": str(uuid.uuid4()), "blocked": ""}
                _RUNTIME[key] = state
        self.state = state
        self.session = state["session"]
        self.proxy = ""
        self.account = {}
        self.query = {"version_code": "20800", "language": "zh", "device_platform": "web",
            "doubao_device_platform": "web", "aid": "497858", "real_aid": "497858", "pkg_type": "release_version",
            "device_id": state["device"], "web_id": state["web"], "pc_version": "3.43.0", "doubao_pc_version": "3.43.0",
            "region": "CN", "sys_region": "CN", "samantha_web": "1", "web_platform": "browser",
            "use-olympus-account": "1", "web_tab_id": str(uuid.uuid4())}
        self.conv = self.cws = self.version = self.idgen = ""
        self.upload_credential = None

    def _warm(self):
        if not self.state["warmed"]:
            with self.session.get(BASE + "/chat/", timeout=(10, 25)) as response:
                response.raise_for_status()
            self.state["warmed"] = True

    def api(self, path, body, timeout=35):
            self._warm()
            r = self.session.post(BASE + path, params=self.query, json=body, timeout=timeout)
            try:
                d = r.json()
            except ValueError:
                raise ProtocolError("接口 %s 返回非 JSON（HTTP %s）" % (path, r.status_code)) from None
            if r.status_code != 200 or d.get("code") != 0:
                raise ProtocolError("接口 %s 失败：code=%s %s" % (path, d.get("code"), str(d.get("msg") or d.get("message") or "登录失效或接口拒绝")[:160]), d.get("code"))
            return d.get("data") or {}

    def get_doc(self, ids=None):
            if not self.conv:
                raise ProtocolError("当前账号尚未设置画布，请点击“新建当前账号画布”或填写该账号的画布链接")
            req = {"conversation_id": self.conv, "need_idgen_session": True}
            if self.cws:
                req["canvas_workspace_id"] = self.cws
            if ids:
                req["item_ids"] = ids
            d = self.api("/creativity/canvas_workspace/doc/get", {"req": req})
            snapshot = d.get("snapshot") or {}
            self.cws = snapshot.get("canvas_workspace_id") or self.cws
            self.version = str(snapshot.get("version") or self.version)
            self.idgen = d.get("idgen_session") or self.idgen
            if not self.cws or not self.version:
                raise ProtocolError("画布快照缺少工作区 ID/版本")
            items = (snapshot.get("doc") or {}).get("items") or {}
            return items if isinstance(items, dict) else {v["id"]: v for v in items}

    def create_canvas(self, title="字字动画分镜画布"):
            data = self.api("/creativity/canvas_workspace/doc/create", {"req": {
                "conversation_id": "0", "title": title, "initial_assets": [],
                "create_new_conversation": True,
                "conversation_init_ext": json.dumps({"agent_task_param": json.dumps({"runtime_type": 1}), "mode_id": "3", "model_item_key": "9", "reasoning_effort": "5"}, separators=(",", ":"))
            }})
            conv = str(data.get("conversation_id") or "")
            if not conv.isdigit() or conv == "0":
                raise ProtocolError("创建画布后未返回会话 ID")
            self.conv = conv
            self.cws = (data.get("snapshot") or {}).get("canvas_workspace_id") or ""
            self.version = ""
            self.idgen = ""
            url = BASE + "/chat/" + conv
            self.session.headers["Referer"] = url
            self.get_doc()
            return url

    def top(self, action, extra=None, payload=None):
            if self.upload_credential is None:
                self.upload_credential = self.api("/alice/resource/prepare_upload", {"tenant_id": "5", "scene_id": "5", "resource_type": 2})
            creds = self.upload_credential
            token = creds["upload_auth_token"]
            query = {"Action": action, "Version": "2018-08-01", "ServiceId": creds["service_id"]}
            query.update(extra or {})
            body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
            method = "POST" if payload is not None else "GET"
            headers = {"x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "x-amz-security-token": token["session_token"]}
            if body:
                headers["x-amz-content-sha256"] = hashlib.sha256(body).hexdigest()
            headers["Authorization"] = signature(method, "/top/v1", query, headers, body, token)
            if body:
                headers["Content-Type"] = "application/json"
            r = self.session.request(method, BASE + "/top/v1", params=query, data=body or None, headers=headers, timeout=45)
            d = r.json()
            err = (d.get("ResponseMetadata") or {}).get("Error")
            if r.status_code != 200 or err or not d.get("Result"):
                raise ProtocolError("%s 失败：%s" % (action, (err or {}).get("Code") or r.status_code))
            return d["Result"]

    def upload(self, path):
            with open(path, "rb") as f:
                raw = f.read()
            with Image.open(path) as im:
                width, height = im.size
            ext = os.path.splitext(path)[1].lower() or ".png"
            result = self.top("ApplyImageUpload", {"NeedFallback": "true", "FileSize": str(len(raw)), "FileExtension": ext, "s": secrets.token_hex(6)})
            address = result.get("UploadAddress") or {}
            stores = address.get("StoreInfos") or []
            hosts = address.get("UploadHosts") or []
            if not stores or not hosts or not address.get("SessionKey"):
                raise ProtocolError("申请上传响应缺少地址或 SessionKey")
            store = stores[0]
            uri = store["StoreUri"]
            headers = {"User-Agent": UA, "Content-Type": "application/octet-stream", "Content-CRC32": "%08x" % (zlib.crc32(raw) & 0xffffffff), "Content-Disposition": 'attachment; filename="undefined"', "Origin": BASE, "Referer": BASE + "/"}
            uid = str(self.account.get("user_id_str") or self.account.get("user_id") or "")
            if uid:
                headers["X-Storage-U"] = uid
            if store.get("Auth"):
                headers["Authorization"] = store["Auth"]
            # Use the server-issued URI/host only, with no Doubao Cookie.
            host = hosts[0]
            if not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
                raise ProtocolError("上传主机格式无效")
            with requests.Session() as storage:
                configure(storage, self.proxy)
                r = storage.post("https://" + host + "/upload/v1/" + uri, data=raw, headers=headers, timeout=120)
                if r.status_code != 200:
                    raise ProtocolError("图片直传失败：HTTP %s" % r.status_code, r.status_code)
                result_body = r.json()
                if result_body.get("code", 0) not in (0, 2000):
                    raise ProtocolError("图片存储拒绝上传：code=%s" % result_body.get("code"))
            commit = self.top("CommitImageUpload", payload={"SessionKey": address["SessionKey"]})
            for entry in commit.get("Results") or []:
                if entry.get("Uri") == uri and entry.get("UriStatus", 2000) not in (2000, 0):
                    raise ProtocolError("图片落库状态异常")
            digest = hashlib.md5(raw).hexdigest()
            self.api("/alice/resource/register", {"tenant_id": "5", "scene_id": "148", "resource_list": [{"uri": uri, "resource_type": 2, "meta": {"image_meta": {"data": {"md5": digest, "identifier": str(uuid.uuid4())}, "parse_extra": {}, "image_info": {"width": width, "height": height, "size": len(raw), "md5": digest, "file_name": os.path.basename(path)}}}}]})
            return {"attachment_type": 1, "image": {"uri": uri, "width": width, "height": height}}

    def node_id(self):
            if not self.idgen:
                self.get_doc()
            if not self.idgen:
                raise ProtocolError("缺少节点 ID 会话")
            return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8)) + "-" + self.idgen + "-0202"

    def create_node(self, nid, title, index, settings):
            for attempt in range(3):
                items = self.get_doc()
                if nid in items:
                    return items[nid]
                ratio = settings.get("ratio", "9:16")
                dimensions = {"9:16": (1440, 2560), "16:9": (2560, 1440), "1:1": (2048, 2048), "3:4": (1536, 2048), "4:3": (2048, 1536), "21:9": (2560, 1097)}
                w, h = dimensions.get(ratio, (1440, 2560))
                y = max([float((v.get("transform") or {}).get("y", 0)) + float((v.get("transform") or {}).get("height", 0)) for v in items.values()] or [0]) + 160
                node = {"id": nid, "type": 102, "title": title or "分镜%03d" % (index + 1), "frame_id": "", "transform": {"x": 304, "y": y, "width": w, "height": h, "rotation": 0, "z_index": len(items), "flip_horizontal": False, "flip_vertical": False}, "status": 1, "version": 1, "created_by": 2, "ext": {}, "asset": {"asset_key": "", "asset_short_url": "", "type": 2, "ext": {}, "status": 0, "video_info": {}}}
                try:
                    d = self.api("/creativity/canvas_workspace/doc/actions", {"req": {"canvas_workspace_id": self.cws, "workspace_version": self.version, "actions": [{"type": 101, "base_version": "0", "target_item": node}]}})
                    if d.get("is_success") is False:
                        raise ProtocolError("节点创建未成功")
                    self.version = str(d.get("workspace_version") or self.version)
                    confirmed = self.get_doc([nid]).get(nid)
                    if not confirmed:
                        raise ProtocolError("节点创建后没有找到对应节点")
                    return confirmed
                except ProtocolError as exc:
                    if exc.code != 11903 or attempt == 2:
                        raise


class DoubaoCanvasClient(RBClient):
    """Queue adapter with pre-POST checkpoints and no automatic regeneration."""
    def __init__(self, profile, key):
        self.profile = validate_profile(profile)
        self.transport = CanvasTransport(key)
        self.images = {}
        self.known = {}
        self.prepared = {}
        self.canvas = None

    def close(self):
        # Other queue/test clients share this in-memory session. Process exit clears it.
        pass

    @property
    def blocked_reason(self):
        return self.transport.state['blocked']

    @blocked_reason.setter
    def blocked_reason(self, value):
        self.transport.state['blocked'] = value

    @staticmethod
    def encode_id(conv, cws, nid):
        return 'dbc_' + base64.urlsafe_b64encode(json.dumps([conv, cws, nid], separators=(',', ':')).encode()).decode().rstrip('=')

    @staticmethod
    def decode_id(jid):
        if not isinstance(jid, str) or not jid.startswith('dbc_'):
            raise ValueError('豆包任务标识无效')
        try:
            value = json.loads(base64.urlsafe_b64decode(jid[4:] + '=' * (-len(jid[4:]) % 4)))
            if len(value) != 3 or not all(isinstance(s, str) and s for s in value): raise ValueError()
            return tuple(value)
        except Exception:
            raise ValueError('豆包任务上下文不完整') from None

    def track(self, rows):
        for row in rows:
            packet = row.get('prepared_submission') or {}
            jid = packet.get('id') or (row.get('job') or {}).get('id')
            if jid:
                self.decode_id(jid)
                self.known[jid] = packet

    def _select(self, jid):
        self.transport.conv, self.transport.cws, nid = self.decode_id(jid)
        return nid

    @staticmethod
    def normalize(jid, node, packet=None):
        asset = node.get('asset') or {}
        key = str(asset.get('asset_key') or '')
        failure = asset.get('gen_task_info') or {}
        done = key.startswith('v')
        failed = asset.get('status') == 3 and failure.get('code') not in (None, 0, '0') and not done
        accepted = bool(key) or asset.get('status') in (1, 2)
        return {'id': jid, 'status': 'done' if done else 'failed' if failed else 'running' if accepted else 'draft',
                'has_video': done, 'accepted': accepted or done or failed,
                'preset': 'seedance2', 'seconds': 15, 'aspect_ratio': '16:9',
                'prompt': (packet or {}).get('operation', {}).get('prompt', ''),
                'error_message': str(failure.get('message') or failure.get('code') or '')[:400] if failed else None,
                'error_code': failure.get('code') if failed else None,
                '_video_info': asset.get('video_info') or {}, '_vid': key if done else ''}

    def jobs(self):
        found = {}
        grouped = {}
        for jid in self.known:
            conv, cws, nid = self.decode_id(jid)
            grouped.setdefault((conv, cws), []).append((jid, nid))
        for (conv, cws), group in grouped.items():
            self.transport.conv, self.transport.cws = conv, cws
            try: items = self.transport.get_doc([nid for _, nid in group])
            except ProtocolError as exc: self._raise(exc)
            for jid, nid in group:
                if nid in items: found[jid] = self.normalize(jid, items[nid], self.known[jid])
        return found

    def detail(self, jid):
        nid = self._select(jid)
        try: items = self.transport.get_doc([nid])
        except ProtocolError as exc: self._raise(exc)
        if nid not in items: raise UpstreamError(404, '原画布节点不存在；不新建任务')
        return self.normalize(jid, items[nid], self.known.get(jid))

    @staticmethod
    def _raise(exc):
        # The ported transport only reports platform status/message, never cookies/tokens.
        detail = re.sub(r'(?i)(sessionid(?:_ss)?|cookie|authorization|token)\s*[:=]\s*[^\s;,]+', r'\1=[隐藏]', str(exc))[:500]
        raise UpstreamError(403 if any(w in detail for w in ['登录', '权限', '额度', '次数']) else 400, detail) from None

    def check(self):
        try: self.transport.api('/alice/resource/prepare_upload', {'tenant_id': '5', 'scene_id': '5', 'resource_type': 2})
        except ProtocolError as exc: self._raise(exc)

    def upload(self, path, digest):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('参考图片已变化，未上传')
        if digest not in self.images:
            try: self.images[digest] = self.transport.upload(str(path))
            except ProtocolError as exc: self._raise(exc)
        return self.images[digest]

    def payload(self, item, refs, request_id, prepared=None):
        validate_submission(self.profile, item)
        if prepared:
            self.decode_id(prepared['id'])
            self.known[prepared['id']] = prepared
            return prepared
        if len(refs) != len(item['bindings']): raise ValueError('参考图数量不一致')
        if self.canvas is None:
            if self.known:
                conv, cws, _ = self.decode_id(next(iter(self.known)))
                self.canvas = (conv, cws)
            else:
                try: self.transport.create_canvas('子夜典当行 · EP01 · Seedance2.0')
                except ProtocolError as exc: self._raise(exc)
                self.canvas = (self.transport.conv, self.transport.cws)
        self.transport.conv, self.transport.cws = self.canvas
        try:
            nid = self.transport.node_id()
            self.transport.create_node(nid, item['unit_id'], len(self.known), {'ratio': '16:9'})
        except ProtocolError as exc: self._raise(exc)
        jid = self.encode_id(*self.canvas, nid)
        packet = {'id': jid, 'request_id': 'studio:' + request_id,
                  'operation': {'canvas_type': 50, 'generate_type': 1, 'prompt': item['prompt'],
                                'attachments': refs, 'use_model': 'seedance_v2.0',
                                'video_param': {'duration': 15, 'ratio': '16:9'}}}
        self.known[jid] = packet
        return packet

    def submit(self, packet):
        if self.blocked_reason: raise UpstreamError(403, self.blocked_reason)
        nid = self._select(packet['id'])
        try:
            node = self.transport.get_doc([nid]).get(nid)
            if not node: raise ProtocolError('已准备节点丢失')
            asset_key = str((node.get('asset') or {}).get('asset_key') or '')
            if asset_key:
                if asset_key != 'task:' + packet['request_id']:
                    raise ProtocolError('节点已绑定任务，停止重复生成')
                return self.normalize(packet['id'], node, packet)
            req = {'canvas_workspace_id': self.transport.cws, 'biding_item': node,
                   'execute_request': {'request_id': packet['request_id'], 'operation': packet['operation'],
                                      'canvas_context': {'conversation_id': self.transport.conv,
                                                         'trigger_scene': 'infinite_canvas_video_generator'}},
                   'callback_args': str(uuid.uuid4()), 'workspace_version': self.transport.version}
            # This is the only video generation POST. Timeouts remain uncertain.
            result = self.transport.api('/creativity/canvas_workspace/tool/exec', {'req': req}, timeout=90)
            if not result.get('task_snapshot'): raise RuntimeError('生成请求未返回明确回执，须续查原节点')
        except ProtocolError as exc:
            self.blocked_reason = '豆包已拒绝本次提交；队列停止创建新任务，请检查当前会话权限或额度。'
            self._raise(exc)
        return {'id': packet['id'], 'status': 'pending', 'has_video': False}

    def download(self, jid, output):
        job = self.detail(jid)
        target = str(job['_video_info'].get('download_url') or '')
        if not job['has_video'] or urlsplit(target).scheme != 'https':
            raise ValueError('原画布尚未返回可下载视频')
        output.parent.mkdir(parents=True, exist_ok=True)
        part = output.with_suffix('.mp4.part'); digest = hashlib.sha256(); size = 0
        # Use the platform-provided result, no watermark decoding or session leakage to CDN.
        with configure(requests.Session()) as cdn:
            with cdn.get(target, stream=True, timeout=(15, 90)) as response:
                response.raise_for_status()
                with part.open('wb') as f:
                    for chunk in response.iter_content(256 * 1024):
                        if chunk: f.write(chunk); digest.update(chunk); size += len(chunk)
        with part.open('rb') as f:
            if size < 1024 or b'ftyp' not in f.read(64): raise ValueError('下载内容不是有效MP4')
        part.replace(output)
        return {'size': size, 'sha256': digest.hexdigest()}
