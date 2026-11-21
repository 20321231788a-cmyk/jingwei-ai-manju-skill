"""Project-wide submission turn and priority lane; never stores credentials."""
import contextlib
import hashlib
import json
import os
import time
from pathlib import Path

from runtime import load_json, save_json

PENDING = {'queued', 'waiting_key', 'capacity_wait'}


def profile_token(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()


def home(root, home_dir=None):
    return Path(home_dir) if home_dir else Path(root)/'制作资料/制作看板'


@contextlib.contextmanager
def submission_turn(root, timeout=180, home_dir=None):
    directory=home(root, home_dir);directory.mkdir(parents=True,exist_ok=True)
    stream=(directory/'.submission.lock').open('a+b')
    stream.seek(0,2)
    if not stream.tell():stream.write(b'0');stream.flush()
    deadline=time.monotonic()+timeout
    try:
        while True:
            stream.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('提交调度锁等待超时')
                time.sleep(.05)
        yield
    finally:
        stream.close()


def publish_ready(root, tokens, now=None, home_dir=None):
    save_json(home(root, home_dir)/'优先队列服务.json',{'pid':os.getpid(),'updated_epoch':time.time() if now is None else now,
                                        'ready_profiles':list(tokens)})


def priority_head(root, now=None, home_dir=None):
    now=time.time() if now is None else now
    target_home=home(root, home_dir)
    lease=target_home/'优先队列服务.json'
    if not lease.exists():return None
    state=load_json(lease)
    if now-state.get('updated_epoch',0)>20:return None
    ready=set(state.get('ready_profiles',[]));pending=[]
    for path in (target_home/'重提任务').glob('*.json'):
        row=load_json(path)
        if row.get('submission_state') not in PENDING|{'sending','uncertain'}:continue
        if row.get('download') or row.get('priority_retry_after',0)>now:continue
        if profile_token(row.get('upstream',{})) not in ready:continue
        pending.append(row)
    return min(pending,key=lambda r:(r.get('created_at',''),r.get('order',0),r['request_id'])) if pending else None


def other_upstream_active(root, base_url):
    """Count registered live work on other upstreams toward the project cap."""
    paths=list((home(root)/'重提任务').glob('*.json'))
    config_path=Path(root)/'tools/rb_video_queue/config.json'
    if config_path.exists():
        config=load_json(config_path)
        directory=(Path(root)/config['batch_dir']/'任务记录').resolve()
        if directory.is_relative_to(Path(root).resolve()):paths.extend(directory.glob('*.json'))
    live=set()
    for path in paths:
        row=load_json(path);upstream=(row.get('upstream')or{}).get('base_url','https://rb.coolhs.com').rstrip('/')
        if upstream==base_url.rstrip('/'):continue
        job=row.get('job')or{}
        if job.get('status') in ('pending','running') or row.get('submission_state') in ('sending','uncertain'):
            live.add((upstream,str(job.get('id')or row['request_id'])))
    return len(live)
