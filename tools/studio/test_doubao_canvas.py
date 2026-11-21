"""Single-session canvas adaptation; all HTTP and generation calls are mocked."""
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from canonical import SKILL, board, plan
from doubao_canvas import DoubaoCanvasClient, ProtocolError, signature
from model import Studio, load_json, save_json
from regeneration import Regenerator
from upstream import DOUBAO_PROFILE, UpstreamError, validate_profile, validate_submission

sys.path.insert(0, str(SKILL / 'scripts'))
from test_build_board import fixture


class FakeTransport:
    def __init__(self, key):
        self.conv = self.cws = '100'
        self.version = self.idgen = '1'
        self.state = {'blocked': ''}
        self.nodes = {}
        self.posts = 0
        self.before_post = lambda: None
        self.timeout = False

    def create_canvas(self, title):
        self.conv, self.cws = '100', 'workspace'

    def node_id(self):
        return 'node' + str(len(self.nodes))

    def create_node(self, nid, *args):
        self.nodes[nid] = {'id': nid, 'asset': {'asset_key': '', 'status': 0}}

    def get_doc(self, ids=None):
        return {n: self.nodes[n] for n in ids or self.nodes if n in self.nodes}

    def upload(self, path):
        return {'attachment_type': 1, 'image': {'uri': 'original-image', 'width': 1672, 'height': 941}}

    def api(self, path, body, **kwargs):
        self.before_post()
        self.posts += 1
        req = body['req']; nid = req['biding_item']['id']
        self.nodes[nid]['asset'] = {'asset_key': 'task:' + req['execute_request']['request_id'], 'status': 1}
        if self.timeout:
            raise requests.Timeout()
        return {'task_snapshot': {'id': nid}}


class DoubaoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.folder = self.root / '测试剧/EP01'; self.folder.mkdir(parents=True)
        self.data = fixture(self.folder)
        g = copy.deepcopy(self.data['units'][0]); g.pop('prompt'); g.pop('prompt_zh')
        g.update(id='SD01', model='seedance2', duration_s=15, directing_summary='甲问路，乙指门。',
                 prompt_text='参考@图片1。镜头1（0—15秒）：甲问路，乙指门。', prompt_language='zh',
                 shots=[{'number': 1, 'start_s': 0, 'end_s': 15, 'description': '甲问路。'}],
                 generation={'protocol': 'doubao-canvas-v1', 'preset': 'reference', 'width': 1920,
                             'height': 1080, 'narrative_seconds': 15, 'adopted_interval': [0, 15]})
        self.data.update(active_model='seedance2', seedance_groups=[g], review_status='user_approved')
        save_json(self.folder / '制作数据.json', self.data)
        self.studio = Studio({'root': self.root, 'canonical': True, 'records': self.root / 'records'})
        self.profile = validate_profile(DOUBAO_PROFILE)
        self.studio.save_profile({'profile': self.profile, 'key': 'test-session-secret'})
        self.patch = patch('doubao_canvas.CanvasTransport', FakeTransport); self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def client(self):
        return DoubaoCanvasClient(self.profile, 'test-session-secret')

    def test_script_preview_without_images_stays_unsubmittable(self):
        self.data['script_only'] = True
        group = self.data['seedance_groups'][0]
        group['references'] = []
        group['prompt_text'] = '镜头1：甲在门前问路，乙转身指门。'
        errors, warnings = board.validate(self.data, self.folder, False)
        self.assertFalse(errors, errors)
        self.assertTrue(any('仅脚本审阅' in warning for warning in warnings))
        errors, _ = board.validate(self.data, self.folder, True)
        self.assertTrue(any('不能提交生成' in error for error in errors))
        save_json(self.folder / '制作数据.json', self.data)
        item, = plan(self.root)['requests']
        self.assertFalse(item['ready'])
        self.assertFalse(item['ready_for_approval'])

    def test_changed_source_cannot_pass_with_stale_embedded_quotes(self):
        source = self.folder / 'source.txt'
        source.write_text('甲说：“先开门。”乙说：“进来吧。”', encoding='utf-8')
        data = copy.deepcopy(self.data)
        data.update(source='source.txt', source_quote_manifest={'1': '先开门。', '2': '进来吧。'},
                    source_quote_classification={'spoken': [1, 2], 'nonspoken': []})
        group = data['seedance_groups'][0]
        group['prompt_text'] = '甲说先开门。乙说进来吧。'
        group['dialogue_events'] = [{'source_quote': 1, 'line': '先开门。'},
                                    {'source_quote': 2, 'line': '进来吧。'}]
        self.assertFalse(board.validate_source_dialogue(data, self.folder))
        source.write_text('甲说：“先开窗。”乙说：“进来吧。”', encoding='utf-8')
        errors = board.validate_source_dialogue(data, self.folder)
        self.assertTrue(any('实际原文' in error for error in errors))
        source.write_text('甲说：“先开门。”乙说：“进来吧。”', encoding='utf-8')
        group['dialogue_events'].pop()
        self.assertTrue(board.validate_source_dialogue(data, self.folder))

    def test_15s_model_bindings_and_full_chinese_editor(self):
        item, = plan(self.root)['requests']
        self.assertEqual(item['requested_model'], 'seedance2'); self.assertTrue(item['ready'])
        client = self.client(); packet = client.payload(item, ['original-ref'], 'request-001')
        self.assertEqual(packet['operation']['use_model'], 'seedance_v2.0')
        self.assertEqual(packet['operation']['video_param'], {'duration': 15, 'ratio': '16:9'})
        self.assertEqual(packet['operation']['prompt'], item['prompt'])
        self.assertEqual(packet['operation']['attachments'], ['original-ref'])
        for key, value in [('model_request_seconds', 30), ('requested_model', 'wan3')]:
            bad = dict(item, **{key: value})
            with self.assertRaises(ValueError): validate_submission(self.profile, bad)
        with self.assertRaises(ValueError): validate_profile(dict(self.profile, base_url='https://other.example'))
        from editing import committed_values
        self.assertEqual(committed_values(self.data['seedance_groups'][0])['chinese_description'], item['prompt'])

    def test_image_upload_signature_encodes_query_and_uses_temporary_credentials(self):
        value = signature('GET', '/top/v1', {'Action': 'ApplyImageUpload', 'Name': 'space here'},
                          {'x-amz-date': '20261115T100000Z', 'x-amz-security-token': 'temporary-token'},
                          b'', {'access_key': 'temporary-access', 'secret_key': 'temporary-secret'})
        self.assertTrue(value.startswith('AWS4-HMAC-SHA256 Credential=temporary-access/'))
        self.assertNotIn('temporary-secret', value)

    def test_checkpoint_before_generation_timeout_recovers_exact_node_no_resend(self):
        item, = self.studio.plan()['requests']
        rid, = self.studio.regenerate({'request_ids': [item['request_id']], 'profile_id': self.profile['id'],
                                      'nonce': 'seedance-queue-001'})['request_ids']
        client = self.client(); client.transport.timeout = True
        def check_checkpoint():
            row = load_json(self.studio.jobs_dir / (rid + '.json'))
            self.assertEqual(row['submission_state'], 'sending')
            self.assertTrue(row['prepared_submission']['id'])
            self.assertEqual(row['prepared_submission']['operation']['prompt'], item['prompt'])
        client.transport.before_post = check_checkpoint
        worker = Regenerator(self.studio, lambda p, k: client)
        with patch('regeneration.other_upstream_active', return_value=1):
            worker.tick()
        self.assertEqual(client.transport.posts, 1)
        self.assertEqual(load_json(self.studio.jobs_dir / (rid + '.json'))['submission_state'], 'uncertain')
        worker.tick(); self.assertEqual(client.transport.posts, 1)
        self.assertEqual(load_json(self.studio.jobs_dir / (rid + '.json'))['submission_state'], 'submitted')
        for p in self.root.rglob('*.json'):
            self.assertNotIn('test-session-secret', p.read_text(encoding='utf-8'))

    def test_rejection_blocks_further_submission_and_original_image_hash_is_checked(self):
        item, = plan(self.root)['requests']; client = self.client()
        packet = client.payload(item, ['ref'], 'request-001')
        def reject(*args, **kwargs): raise ProtocolError('当前会话次数不足', 3)
        client.transport.api = reject
        with self.assertRaises(UpstreamError): client.submit(packet)
        self.assertTrue(client.blocked_reason)
        with self.assertRaises(UpstreamError): client.submit(packet)
        f = self.folder / 'input.png'; f.write_bytes(b'original')
        with self.assertRaises(ValueError): client.upload(f, 'changed')
        result = client.upload(f, hashlib.sha256(b'original').hexdigest())
        self.assertEqual(result['image']['uri'], 'original-image')

    def test_restart_tracks_frozen_workspace_and_node(self):
        item, = plan(self.root)['requests']; first = self.client()
        packet = first.payload(item, ['ref'], 'request-001')
        restored = self.client(); restored.transport.nodes = first.transport.nodes
        restored.track([{'prepared_submission': packet}])
        self.assertEqual(restored.detail(packet['id'])['status'], 'draft')
        self.assertFalse(restored.detail(packet['id'])['accepted'])


if __name__ == '__main__': unittest.main()
