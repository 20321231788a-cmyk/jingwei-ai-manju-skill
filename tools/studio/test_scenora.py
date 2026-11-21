"""Mock tests for scenora.ink OpenAPI v1 adapter; no real credentials or paid requests."""
import base64
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from canonical import SKILL, board, plan
from model import Studio, load_json, save_json
from regeneration import Regenerator
from upstream import SCENORA_SEEDANCE_FACE_PROFILE, SCENORA_WAN3_PRO_PROFILE, ScenoraClient, UpstreamError, matches, validate_profile, validate_submission

sys.path.insert(0, str(SKILL / 'scripts'))
from test_build_board import fixture


class FakeScenora(ScenoraClient):
    def __init__(self, profile, key):
        super().__init__(profile, key)
        self.remote = {}
        self.posts = 0
        self.uploaded_bodies = []

    def api(self, method, path, **kw):
        if method == 'GET' and path == '/v1/service-status':
            return {'enabled': True, 'simulation': False, 'models': {'wan3-pro': {'enabled': True, 'reason': ''}}}
        if method == 'GET' and path == '/v1/balance':
            return {'currency': 'POINTS', 'unit_scale': 100, 'available_units': 15000, 'reserved_units': 0}
        if method == 'POST' and path == '/v1/videos/quote':
            return {'model': kw['json']['model'], 'price_units': 1500, 'pricing_revision': 'rev-wan3pro', 'sufficient': True}
        if method == 'POST' and path == '/v1/assets':
            self.uploaded_bodies.append(kw['json'])
            return {'asset': {'id': f'asset_{len(self.uploaded_bodies)}'}}
        if method == 'GET' and path == '/v1/videos':
            return {'total': len(self.remote), 'offset': 0, 'limit': 200, 'tasks': list(self.remote.values())}
        if method == 'GET' and path.startswith('/v1/videos/'):
            jid = path.rsplit('/', 1)[1]
            return self.remote[jid]
        if method == 'POST' and path == '/v1/videos/generations':
            self.posts += 1
            body = kw['json']
            task = {
                'id': 'task_wan3pro_001', 'model': body['model'], 'status': 'queued',
                'billing': 'reserved', 'price_units': 1500, 'client_reference': body['client_reference'],
                'prompt': body['prompt'], 'duration': body['duration'], 'resolution': body['resolution'],
                'ratio': body['ratio'], 'reference_asset_ids': body['reference_asset_ids'],
                'created_at': '2026-11-18T04:00:00Z',
            }
            self.remote[task['id']] = task
            return task
        raise AssertionError(f'Unexpected request: {method} {path}')

    def download(self, jid, output):
        content = b'\0\0\0\x18ftypisom' + b'0' * 2048
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


class ScenoraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / '测试剧/EP01'
        self.folder.mkdir(parents=True)
        self.data = fixture(self.folder)
        self.data.update(active_model='seedance2', review_status='user_approved')
        self.data['seedance_groups'] = [{
            **copy.deepcopy(self.data['units'][0]),
            'id': 'DB001', 'model': 'seedance2', 'duration_s': 15,
            'directing_summary': '甲问路，乙指向门口。',
            'prompt_text': '@图片1。镜头1：甲问路。',
            'dialogue_events': [{'start_s': 0.2, 'end_s': 2.0, 'line': '请问怎么走', 'text': '请问怎么走', 'performance': '平静发问'}],
            'shots': [{'number': 1, 'start_s': 0, 'end_s': 15, 'description': '甲问路。'}],
        }]
        self.data['seedance_groups'][0].pop('prompt', None)
        self.data['seedance_groups'][0].pop('prompt_zh', None)
        g = copy.deepcopy(self.data['units'][0])
        g.pop('prompt'); g.pop('prompt_zh')
        g.update(
            id='W01', model='wan3', duration_s=30,
            directing_summary='甲问路，乙在门边指方向。',
            prompt_text='图1提供甲的身份。\n分镜1（0.00—30.00秒）：甲问路，乙指向门口。',
            dialogue_events=[{'start_s': 0.2, 'end_s': 2.0, 'line': '请问怎么走', 'text': '请问怎么走', 'performance': '平静发问'}],
            source_units=['U01', 'U02'],
            source_revisions={u['id']: board.source_revision(u) for u in self.data['units']},
            shots=[{'number': 1, 'start_s': 0, 'end_s': 30, 'description': '甲问路，乙指向门口。'}],
            generation={'protocol': 'scenora-v1', 'preset': 'reference', 'width': 1920, 'height': 1080,
                        'narrative_seconds': 30, 'adopted_interval': [0, 30]},
        )
        self.data['generation_groups'] = [g]
        save_json(self.folder / '制作数据.json', self.data)
        self.studio = Studio({'root': self.root, 'canonical': True, 'records': self.root / 'records'})
        self.profile = validate_profile(SCENORA_WAN3_PRO_PROFILE)
        self.studio.save_profile({'profile': self.profile, 'key': 'sk_test_secret_token'})

    def tearDown(self):
        self.temp.cleanup()

    def test_validation_payload_and_branch_queue_execution(self):
        item, = plan(self.root, model='wan3')['requests']
        self.assertEqual((item['requested_model'], item['model_request_seconds'], item['width'], item['height']), ('wan3', 30, 1920, 1080))
        self.assertTrue(item['ready'])
        bad_len = {**item, 'prompt': 'x' * 5001}
        with self.assertRaisesRegex(ValueError, '5000'):
            validate_submission(self.profile, bad_len)
        bad_dur = {**item, 'model_request_seconds': 15}
        with self.assertRaisesRegex(ValueError, 'wan3-pro'):
            validate_submission(self.profile, bad_dur)

        client = FakeScenora(self.profile, 'sk_test_secret_token')
        payload = client.payload(item, ['asset_1'], 'local-req-1')
        self.assertEqual((payload['model'], payload['duration'], payload['resolution'], payload['ratio']), ('wan3-pro', 30, '1080p', '16:9'))
        self.assertEqual((payload['expected_price_units'], payload['expected_pricing_revision']), (1500, 'rev-wan3pro'))
        self.assertEqual(payload['reference_asset_ids'], ['asset_1'])
        self.assertTrue(payload['client_reference'].startswith('studio-'))

        ids = self.studio.regenerate({'request_ids': [item['request_id']], 'profile_id': self.profile['id'],
                                      'nonce': 'scenora-queue-test-01', 'model': 'wan3'})['request_ids']
        fake = FakeScenora(self.profile, 'sk_test_secret_token')
        worker = Regenerator(self.studio, lambda p, k: fake)
        worker.tick()
        self.assertEqual(fake.posts, 1)
        self.assertEqual(len(fake.uploaded_bodies), 1)
        self.assertNotIn('data:', fake.uploaded_bodies[0]['base64'])
        fake.remote['task_wan3pro_001']['status'] = 'completed'
        worker.tick()
        self.assertEqual(fake.posts, 1)
        row = load_json(self.studio.jobs_dir / (ids[0] + '.json'))
        self.assertTrue(row['download'])
        for p in self.root.rglob('*.json'):
            self.assertNotIn('sk_test_secret_token', p.read_text(encoding='utf-8'))

    def test_upload_checks_size_and_redacts_key(self):
        c = ScenoraClient(self.profile, 'sk_test_secret_token')
        resp = Mock(ok=False, is_redirect=False, status_code=401)
        resp.json.return_value = {'error': {'message': '无效令牌 sk_test_secret_token'}}
        c.session.request = Mock(return_value=resp)
        with self.assertRaises(UpstreamError) as raised:
            c.api('GET', '/v1/balance')
        self.assertNotIn('sk_test_secret_token', str(raised.exception))
        p = self.root / 'small.png'
        Image.new('RGB', (400, 400), 'white').save(p)
        raw = p.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with patch.object(c, 'api', return_value={'asset': {'id': 'asset_ok'}}) as api:
            self.assertEqual(c.upload(p, digest), 'asset_ok')
            sent = api.call_args.kwargs['json']
            self.assertEqual(base64.b64decode(sent['base64']), raw)

    def test_seedance_face_15s_720p_validation_and_payload(self):
        p = validate_profile(SCENORA_SEEDANCE_FACE_PROFILE)
        self.data['seedance_groups'][0]['generation'] = {
            'protocol': 'scenora-v1', 'preset': 'reference', 'width': 1280, 'height': 720,
            'narrative_seconds': 15, 'adopted_interval': [0, 15],
        }
        save_json(self.folder / '制作数据.json', self.data)
        item, = plan(self.root)['requests']
        self.assertTrue(item['ready'])
        self.assertEqual((item['requested_model'], item['model_request_seconds'], item['width'], item['height']), ('seedance2', 15, 1280, 720))
        fake = FakeScenora(p, 'sk_test_secret_token')
        payload = fake.payload(item, ['asset_sd1'], 'sd-req-1')
        self.assertEqual((payload['model'], payload['duration'], payload['resolution'], payload['ratio']), ('seedance-2.0-face', 15, '720p', '16:9'))
        bad_res = {**item, 'width': 1920, 'height': 1080}
        with self.assertRaisesRegex(ValueError, '480p/720p'):
            validate_submission(p, bad_res)


if __name__ == '__main__':
    unittest.main()
