"""Submit through the running studio queue; dry-run unless --execute is given."""
import argparse
import os
import uuid
from urllib.parse import urlsplit
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Studio URL (defaults to matching running project port or 127.0.0.1:8766)')
    parser.add_argument('--project', help='Drama directory name when connecting to a per-drama studio instance')
    parser.add_argument('--episode', required=True, help='Episode id from /api/state')
    parser.add_argument('--units', nargs='+', help='Local unit IDs, e.g. U01 U02; omitted selects episode')
    parser.add_argument('--profile', help='Saved upstream profile id; defaults to active profile')
    parser.add_argument('--key-env', help='Read credential from this environment variable; never put a key on command line')
    parser.add_argument('--key-prompt', action='store_true', help='Read credential with an echo-free prompt; never saves it')
    parser.add_argument('--cancel-request', help='Cancel this exact queued Wan request for a user-requested replacement')
    parser.add_argument('--execute', action='store_true', help='Authorize paid generation of the displayed selection')
    args = parser.parse_args()
    if args.cancel_request:
        import getpass
        from model import Studio, load_json, save_json, stamp, studio_config
        from upstream import WanPortalClient
        from regeneration import brief
        studio=Studio(studio_config(args.project) if args.project else None)
        row_path=studio.jobs_dir/(args.cancel_request+'.json')
        if row_path.parent!=studio.jobs_dir or not row_path.is_file():parser.error('未找到准确的队列记录。')
        row=load_json(row_path)
        if row.get('episode_id')!=args.episode or row['upstream']['protocol']!='wan-portal-v1':parser.error('取消范围不匹配。')
        if not args.execute:
            print('仅预览取消：'+args.cancel_request);return 0
        key=getpass.getpass('WAN_CARD: ') if args.key_prompt else os.environ.get(args.key_env or '')
        if not key:parser.error('取消需要原卡密，未执行。')
        client=WanPortalClient(row['upstream'],key)
        try:
            job,remaining=client.cancel(row['job']['id'])
            row=load_json(row_path);row.update(submission_state='cancelled',job=brief(job),cancelled_at=stamp(),
                note='按用户整集中文要求取消英文候车任务；上游已确认退回次数，历史请求与原提示词保留。')
            row['cancel_reason']='用户要求全部使用中文提交'
            save_json(row_path,row)
            print('已取消原候车任务；当前剩余次数：'+str(remaining));return 0
        finally:client.close()
    if not args.url:
        from launch import find_target_port
        args.url = f'http://127.0.0.1:{find_target_port(args.project)}'
    parsed = urlsplit(args.url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        parser.error('--url 必须为本机看板地址')
    base = args.url.rstrip('/')
    session = requests.Session();session.trust_env = False
    def api(path, data=None):
        response = session.get(base+'/api/'+path, timeout=30) if data is None else session.post(base+'/api/'+path, json=data, timeout=30)
        value = response.json()
        if not response.ok: raise ValueError(value.get('error', '本地操作失败'))
        return value
    try:
        boot = api('bootstrap')
        session.headers.update({'Origin': base, 'X-Studio-Token': boot['csrf']})
        ep = api('episode/'+args.episode)
        wanted = set(args.units or [])
        items = [q for q in ep['requests'] if not wanted or q['unit_id'] in wanted or q['unit_id'].removeprefix(args.episode+'_') in wanted]
        if not items: raise ValueError('没有匹配镜头')
        if wanted and any(not any(w in (q['unit_id'], q['unit_id'].removeprefix(args.episode+'_')) for q in items) for w in wanted):
            raise ValueError('包含不存在的镜头，未提交')
        profile = next((p for p in boot['profiles']['profiles'] if p['id'] == (args.profile or boot['profiles']['active'])), None)
        if profile is None: raise ValueError('接口配置不存在')
        print(f'接口：{profile["name"]} · {profile["base_url"]}{profile["jobs_path"]}')
        print(f'协议：{profile["protocol"]} · reference映射：{profile["preset_map"]["reference"]}')
        if profile['protocol'] == 'sparkcine-v1':
            print(f'分辨率：{profile.get("video_resolution", "720p")} · 提示词优化：关闭')
        for q in items:
            interval = q.get('adopted_interval', [0, q['model_request_seconds']])
            print(f'{q["unit_id"]}: 请求{q["model_request_seconds"]}秒 · {q["preset"]} · {q["width"]}×{q["height"]} · 剪辑采用{interval[0]:g}–{interval[1]:g}秒 · {"可提交" if q.get("ready", True) or q.get("ready_for_approval") else "待终审/补齐"}')
        if not args.execute:
            print('仅预览，未写队列、未提交。');return 0
        if any(q.get('ready') is False and not q.get('ready_for_approval') for q in items): raise ValueError('所选镜头尚未完成审阅或资料不完整')
        if args.key_env or args.key_prompt:
            if args.key_env and args.key_prompt: raise ValueError('请选择环境变量或隐藏输入中的一种。')
            if args.key_prompt:
                import getpass
                key = getpass.getpass('WAN_CARD: ')
            else: key = os.environ.get(args.key_env)
            if not key: raise ValueError('指定环境变量未设置')
            state = api('profiles', {'profile': profile, 'key': key})
            profile = next(p for p in state['profiles'] if p['id'] == state['active'])
        result = api('regenerate', {'request_ids': [q['request_id'] for q in items], 'profile_id': profile['id'], 'nonce': uuid.uuid4().hex, 'approve_reviewed_selection': True})
        print('已登记：' + '、'.join(result['request_ids']))
        return 0
    except (ValueError, requests.RequestException) as error:
        print('未完成：' + (str(error) if isinstance(error, ValueError) else '无法连接本地服务，请启动看板后重试'))
        return 1
    finally:
        session.close()


if __name__ == '__main__':
    raise SystemExit(main())
