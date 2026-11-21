"""Start a drama-scoped production studio viewer/queue; never cross-mix projects."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1].resolve()
sys.path.insert(0, str(HERE))
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def project_port(project=None):
    if not project:
        return 8766
    return 8770 + int(hashlib.sha256(project.encode('utf-8')).hexdigest()[:4], 16) % 80


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def available(url, project=None):
    try:
        with _DIRECT_OPENER.open(url + '/api/bootstrap', timeout=1.2) as r:
            data = json.load(r)
            return (bool(data.get('csrf'))
                    and Path(data.get('workspace', '')).resolve() == ROOT
                    and (data.get('project') or '') == (project or ''))
    except Exception:
        return False


def find_target_port(project=None, explicit_port=None):
    if explicit_port:
        return explicit_port
    preferred = project_port(project)
    if not port_free(preferred) and available(f'http://127.0.0.1:{preferred}', project):
        return preferred
    candidates = ([p for p in range(8770, 8860) if p != preferred] + [8766, 8767, 8768, 8769]) if project else [8766, 8767, 8768]
    for port in candidates:
        if not port_free(port) and available(f'http://127.0.0.1:{port}', project):
            return port
    if port_free(preferred):
        return preferred
    for port in range(8770, 8900):
        if port_free(port):
            return port
    return preferred


def choose_project_interactively():
    from canonical import discover_projects
    projects = discover_projects(ROOT)
    if len(projects) == 1:
        return projects[0]['name']
    if not projects:
        return None
    if not sys.stdin or not sys.stdin.isatty():
        return None
    print('\n当前工作区共有以下独立作品（建议每部作品单独打开，加载更快、互不混淆）：')
    for idx, item in enumerate(projects, 1):
        print(f'  {idx}. {item["name"]}（{item["episodes"]} 集）')
    print('  0. 打开全部作品汇总看板')
    while True:
        choice = input(f'请输入编号 [1-{len(projects)}，默认 1]: ').strip()
        if choice == '':
            return projects[0]['name']
        if choice == '0':
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(projects):
            return projects[int(choice) - 1]['name']
        print('输入无效，请重新输入编号。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', help='Open dashboard scoped to a single drama directory')
    parser.add_argument('--all', action='store_true', help='Open combined workspace dashboard for all dramas')
    parser.add_argument('--port', type=int, help='Bind/reuse explicit local port')
    parser.add_argument('--no-open', action='store_true', help='Start/verify server without launching a browser tab')
    args = parser.parse_args()

    project = None if args.all else args.project
    if project is None and not args.all:
        project = choose_project_interactively()

    if project:
        proj_dir = (ROOT / project).resolve()
        if not proj_dir.is_relative_to(ROOT) or not proj_dir.is_dir():
            raise SystemExit(f'未找到作品目录：{project}')
        project = proj_dir.relative_to(ROOT).as_posix()

    port = find_target_port(project, args.port)
    url = f'http://127.0.0.1:{port}'
    if port_free(port) or not available(url, project):
        logs = (ROOT / project / '制作资料/制作看板') if project else (ROOT / '制作资料/制作看板')
        logs.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # Never inherit an agent's credentials accidentally.
        for key in ('RB_TASK_KEY', 'RB_NEW_BATCH_KEY', 'scenora_API_KEY', 'SCENORA_API_KEY'):
            env.pop(key, None)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        cmd = [sys.executable, str(HERE / 'server.py'), '--port', str(port)]
        if project:
            cmd += ['--project', project]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        with (logs / '服务日志.txt').open('ab') as output:
            subprocess.Popen(cmd, cwd=ROOT, env=env,
                             stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                             close_fds=True, creationflags=flags, start_new_session=os.name != 'nt')
        for _ in range(80):
            if not port_free(port) and available(url, project):
                break
            time.sleep(0.15)
        else:
            log_rel = logs.relative_to(ROOT).as_posix() + '/服务日志.txt'
            raise SystemExit(f'看板未能启动，请查看 {log_rel}')

    if not args.no_open:
        webbrowser.open(url + '/?view=script')
    print(f'制作看板已打开：{url}' + (f' 【{project}】' if project else ' 【全部作品】'))


if __name__ == '__main__':
    main()
