"""Atomic task snapshots and workspace paths; no credentials or second plan file."""
import json
import os
import uuid
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, value):
    path = Path(path)
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        temporary.write_text(content, encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def settings(config_path=None):
    root = Path(__file__).resolve().parents[2]
    return {'root': root, 'canonical': True,
            'records': root/'制作资料/制作看板/历史任务'}
