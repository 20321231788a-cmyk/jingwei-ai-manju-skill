"""Regression tests for studio P0+P1 enhancements (assets, annotations, SRT, pricing)."""
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import requests

from canonical import SKILL, catalog, episode
from exporter import build_srt, format_srt_time
from model import Studio, save_json
from server import Server
from upstream import DEFAULT_PROFILE, validate_profile

sys.path.insert(0, str(SKILL / 'scripts'))
from test_build_board import fixture


class StudioEnhancementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        ep1 = self.root / '测试剧/EP001'
        ep2 = self.root / '测试剧/EP002'
        ep1.mkdir(parents=True)
        ep2.mkdir(parents=True)

        d1 = fixture(ep1)
        d1['project'] = '测试剧'
        d1['episode'] = 'EP001'
        d1['review_status'] = 'reviewed'
        d1['references'].append({'id': 'MISS1', 'type': 'prop', 'path': 'missing.png', 'purpose': '缺失道具', 'verified': False})
        save_json(ep1 / '制作数据.json', d1)

        d2 = fixture(ep2)
        d2['project'] = '测试剧'
        d2['episode'] = 'EP002'
        d2['review_status'] = 'reviewed'
        d2['references'][0]['path'] = '../EP001/人物图.png'
        save_json(ep2 / '制作数据.json', d2)

        self.ep1_board = ep1 / '制作数据.json'
        self.s = Studio({'root': self.root, 'canonical': True, 'records': self.root / 'records'})
        self.eps = catalog(self.root)[0]
        self.eid1 = next(e['id'] for e in self.eps if 'EP001' in e['title'])

    def tearDown(self):
        self.temp.cleanup()

    def test_assets_aggregation_dedup_and_reference_urls(self):
        res = self.s.assets()['assets']
        shared = [a for a in res if a['path'].endswith('人物图.png')]
        self.assertEqual(len(shared), 1)
        self.assertEqual(len(shared[0]['episodes']), 2)
        self.assertTrue(shared[0]['url'].startswith('/project/'))
        missing = [a for a in res if a['id'] == 'MISS1']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['url'], '')
        ep = episode(self.root, self.eid1)
        self.assertTrue(any(r['id'] == 'C01' and r['url'].startswith('/project/') for r in ep['reference_assets']))

    def test_annotations_csrf_persistence_and_source_board_untouched(self):
        before_sha = hashlib.sha256(self.ep1_board.read_bytes()).hexdigest()
        server = Server(('127.0.0.1', 0), self.s)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        base = f'http://127.0.0.1:{server.server_port}'
        headers = {'Origin': base, 'X-Studio-Token': server.csrf}
        try:
            self.assertEqual(requests.post(base + '/api/annotations', json={'kind': 'video', 'id': 'v1', 'tag': 'star'}).status_code, 403)
            r = requests.post(base + '/api/annotations', json={'kind': 'video', 'id': 'v1', 'tag': 'star', 'note': '口型很准'}, headers=headers)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()['videos']['v1']['tag'], 'star')
            r2 = requests.post(base + '/api/annotations', json={'kind': 'unit', 'id': self.eid1 + '_U01', 'review': 'fix', 'note': '第2秒调整'}, headers=headers)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json()['units'][self.eid1 + '_U01']['review'], 'fix')
            fetched = requests.get(base + '/api/annotations').json()
            self.assertEqual(fetched['videos']['v1']['note'], '口型很准')
            cleared = requests.post(base + '/api/annotations', json={'kind': 'video', 'id': 'v1', 'tag': '', 'note': ''}, headers=headers).json()
            self.assertNotIn('v1', cleared['videos'])
            with self.assertRaises(ValueError):
                self.s.save_annotation({'kind': 'video', 'id': 'v1', 'tag': 'invalid'})
        finally:
            server.shutdown()
            server.server_close()
            t.join()
        after_sha = hashlib.sha256(self.ep1_board.read_bytes()).hexdigest()
        self.assertEqual(before_sha, after_sha)

    def test_export_srt_dialogue_events_and_fallback_with_trim_offsets(self):
        ep_dir = self.root / '测试剧/EP003'
        ep_dir.mkdir(parents=True)
        data = fixture(ep_dir)
        data['project'] = '测试剧'
        data['episode'] = 'EP003'
        data['active_model'] = 'wan3'
        data['units'] = []
        data['thrill_plan'] = {
            'opening_hook_3s': '开场暴击，直接推翻桌子。',
            'core_pain_point': '当众羞辱',
            'payoff_climax': '当场反杀“这命我收了！”',
            'thrill_level': 8,
            'slice_highlight': '金句“这命我收了！”',
            'ending_hook': '门外警笛响起',
        }
        data['generation_groups'] = [
            {
                'id': 'W01',
                'model': 'wan3',
                'title': '开场反杀',
                'source_locator': '第1场',
                'duration_s': 30,
                'dramatic_arc': '挑衅→加压→反杀',
                'directing_summary': '大姨拍桌，林昊夺回契约并反杀。',
                'scene': '公园',
                'framing': '中景切近景',
                'action': '拍桌压迫后抬手掀翻。',
                'camera': '俯拍切仰拍',
                'sound': '拍桌脆响',
                'continuity': '接下一段',
                'references': ['C01'],
                'shots': [
                    {'number': 1, 'start_s': 0, 'end_s': 15, 'description': '大姨拍桌逼问。'},
                    {'number': 2, 'start_s': 15, 'end_s': 30, 'description': '主角反击立威。'},
                ],
                'dialogue_events': [
                    {'start_s': 0.5, 'end_s': 3.0, 'speaker': '反派', 'performance': '冷笑逼近', 'line': '少糊弄人！', 'text': '少糊弄人！'},
                    {'start_s': 12.0, 'end_s': 16.0, 'speaker': '主角', 'performance': '霸气反压', 'line': '明天双倍赔你！', 'text': '明天双倍赔你！'},
                ],
                'dialogue': ['0.5–3.0秒，反派：少糊弄人！', '12.0–16.0秒，主角：明天双倍赔你！'],
                'prompt_text': '图1人物。\n\n0–15秒，主角拍桌对峙，台词“少糊弄人！”\n\n15–30秒，骤切近景，主角反击：“明天双倍赔你！”并说出“这命我收了！”',
            },
            {
                'id': 'W02',
                'model': 'wan3',
                'title': '后续收口',
                'source_locator': '第2场',
                'duration_s': 30,
                'dramatic_arc': '余波→收口→断钩',
                'directing_summary': '林昊收回令牌起身转身。',
                'scene': '公园',
                'framing': '近景',
                'action': '扣腕震退并转身离场。',
                'camera': '低仰拍',
                'sound': '木牌震鸣',
                'continuity': '出画',
                'references': ['C01'],
                'shots': [
                    {'number': 1, 'start_s': 0, 'end_s': 15, 'description': '扣腕震退对手。'},
                    {'number': 2, 'start_s': 15, 'end_s': 30, 'description': '转身留悬念。'},
                ],
                'dialogue': ['0.50–4.20秒，林昊：这命我收了！'],
                'prompt_text': '图1人物。\n\n0–15秒，主角扣腕震退对手，喊出“这命我收了！”\n\n15–30秒，转身推门留悬念。',
            },
        ]
        save_json(ep_dir / '制作数据.json', data)
        eid3 = next(e['id'] for e in catalog(self.root)[0] if 'EP003' in e['title'])
        rec_dir = self.root / 'records'
        rec_dir.mkdir(exist_ok=True)
        mp4_1 = ep_dir / 'w01.mp4'
        mp4_2 = ep_dir / 'w02.mp4'
        mp4_1.write_bytes(b'fake-mp4-1')
        mp4_2.write_bytes(b'fake-mp4-2')
        save_json(rec_dir / 'r1.json', {
            'request_id': 'req-w01', 'episode_id': eid3, 'unit_id': eid3 + '_W01',
            'model_request_seconds': 30, 'download': {'path': '测试剧/EP003/w01.mp4'},
        })
        save_json(rec_dir / 'r2.json', {
            'request_id': 'req-w02', 'episode_id': eid3, 'unit_id': eid3 + '_W02',
            'model_request_seconds': 30, 'download': {'path': '测试剧/EP003/w02.mp4'},
        })
        self.s.invalidate()
        videos = self.s.snapshot(force=True)['videos']
        v1 = next(v for v in videos if v['request_id'] == 'req-w01')
        v2 = next(v for v in videos if v['request_id'] == 'req-w02')

        result = build_srt(self.s, {
            'name': '第三集初剪',
            'episode_id': eid3,
            'clips': [
                {'video_id': v1['id'], 'start': 1.0, 'end': 14.0},
                {'video_id': v2['id'], 'start': 0.0, 'end': 5.0},
            ],
        })
        self.assertEqual(format_srt_time(1.234), '00:00:01,234')
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['filename'], '第三集初剪.srt')
        self.assertIn('00:00:00,000 --> 00:00:02,000\n少糊弄人！', result['srt'])
        self.assertIn('00:00:11,000 --> 00:00:13,000\n明天双倍赔你！', result['srt'])
        self.assertIn('00:00:13,500 --> 00:00:17,200\n这命我收了！', result['srt'])

    def test_profile_optional_price_per_second_validation(self):
        base = validate_profile(DEFAULT_PROFILE)
        self.assertNotIn('price_per_second', base)
        zero_price = validate_profile({**DEFAULT_PROFILE, 'price_per_second': 0})
        self.assertNotIn('price_per_second', zero_price)
        priced = validate_profile({**DEFAULT_PROFILE, 'price_per_second': 0.35})
        self.assertEqual(priced['price_per_second'], 0.35)
        with self.assertRaises(ValueError):
            validate_profile({**DEFAULT_PROFILE, 'price_per_second': -1})
        with self.assertRaises(ValueError):
            validate_profile({**DEFAULT_PROFILE, 'price_per_second': True})

    def test_persistent_dpapi_credentials_and_no_json_leakage(self):
        secret = 'sk-test-persist-secret-7890'
        prof = {
            'id': 'custom-gateway',
            'name': '测试真接口',
            'base_url': 'https://api.example.com/v1',
            'model': 'wan3-pro',
            'video_resolution': '1080p',
        }
        state = self.s.save_profile({'profile': prof, 'key': secret})
        saved = next(p for p in state['profiles'] if p['id'] == 'custom-gateway')
        self.assertEqual(saved['protocol'], 'openai-video-v1')
        self.assertTrue(saved['credential_ready'])
        self.assertEqual(saved['key_masked'], 'sk-t••••7890')

        # Secrets must never appear in any JSON file under studio home.
        for jpath in self.s.home.rglob('*.json'):
            self.assertNotIn(secret, jpath.read_text(encoding='utf-8'))
        self.assertTrue(self.s.credentials_file.is_file())

        # Recreate Studio from disk -> saved key must automatically load.
        restarted = Studio({'root': self.root, 'canonical': True, 'records': self.root / 'records'})
        reloaded = next(p for p in restarted.profiles()['profiles'] if p['id'] == 'custom-gateway')
        self.assertTrue(reloaded['credential_ready'])
        self.assertEqual(reloaded['key_masked'], 'sk-t••••7890')
        self.assertEqual(restarted.keys[restarted.profile_key({k: v for k, v in reloaded.items() if k not in ('credential_ready', 'key_masked')})], secret)

    def test_delete_profile_csrf_and_key_cleanup(self):
        self.s.save_profile({'profile': {'id': 'p1', 'name': 'A', 'base_url': 'https://a.example', 'model': 'm1'}, 'key': 'k1-secret'})
        server = Server(('127.0.0.1', 0), self.s)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        base = f'http://127.0.0.1:{server.server_port}'
        headers = {'Origin': base, 'X-Studio-Token': server.csrf}
        try:
            self.assertEqual(requests.post(base + '/api/profiles/delete', json={'id': 'p1'}).status_code, 403)
            res = requests.post(base + '/api/profiles/delete', json={'id': 'p1'}, headers=headers)
            self.assertEqual(res.status_code, 200)
            ids = [p['id'] for p in res.json()['profiles']]
            self.assertNotIn('p1', ids)
            # Delete remaining seeded default profile too -> profiles list may become empty cleanly.
            for pid in ids:
                res = requests.post(base + '/api/profiles/delete', json={'id': pid}, headers=headers)
                self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()['profiles'], [])
            self.assertEqual(res.json()['active'], '')
        finally:
            server.shutdown(); server.server_close(); t.join()

        restarted = Studio({'root': self.root, 'canonical': True, 'records': self.root / 'records'})
        self.assertEqual(restarted.profiles()['profiles'], [])
        self.assertEqual(restarted.keys, {})

    def test_fetch_models_openai_v1_dedup_scenora_and_redaction(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class MockUpstream(BaseHTTPRequestHandler):
            seen_paths = []
            def log_message(self, *a): pass
            def do_GET(self):
                MockUpstream.seen_paths.append(self.path)
                auth = self.headers.get('Authorization', '')
                if auth == 'Bearer bad-secret-xyz':
                    body = json.dumps({'error': {'message': 'bad key bad-secret-xyz'}}).encode()
                    self.send_response(401); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
                if self.path == '/v1/models':
                    body = json.dumps({'data': [{'id': 'gpt-4o'}, {'id': 'wan3-pro'}, {'id': 'seedance-2.0'}]}).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
                self.send_response(404); self.end_headers()

        srv = HTTPServer(('127.0.0.1', 0), MockUpstream)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            url_with_v1 = f'http://127.0.0.1:{srv.server_port}/v1'
            res = self.s.fetch_models({'base_url': url_with_v1, 'key': 'sk-good-123'})
            self.assertTrue(res['ok'])
            # /v1 + /v1/models must dedup to /v1/models, and video models sort before chat models.
            self.assertIn('/v1/models', MockUpstream.seen_paths)
            self.assertNotIn('/v1/v1/models', MockUpstream.seen_paths)
            ids = [m['id'] for m in res['models']]
            self.assertEqual(ids[:2], ['seedance-2.0', 'wan3-pro'])
            self.assertIn('gpt-4o', ids)

            # test_profile with openai-video-v1 uses real .models() check without touching stored keys
            t_res = self.s.test_profile({'profile': {'id': 'probe', 'name': 'Probe', 'base_url': url_with_v1, 'model': 'wan3-pro'}, 'key': 'sk-good-123'})
            self.assertTrue(t_res['ok'])
            self.assertEqual(len(t_res['models']), 3)

            with self.assertRaises(ValueError) as err:
                self.s.fetch_models({'base_url': url_with_v1, 'key': 'bad-secret-xyz'})
            self.assertNotIn('bad-secret-xyz', str(err.exception))
        finally:
            srv.shutdown(); srv.server_close(); t.join()

        # Mock scenora /v1/service-status via custom fetcher
        res_sc = self.s.fetch_models(
            {'base_url': 'https://scenora.ink', 'key': 'sk_sc'},
            fetcher=lambda prof, k: [{'id': 'wan3-pro', 'label': 'wan3-pro', 'enabled': True}],
        )
        self.assertEqual(res_sc['detected_protocol'], 'scenora-v1')

    def test_canonical_board_files_skips_nested_sub_board(self):
        ep_root = self.root / '测试剧/OP001'
        nested = ep_root / '分镜脚本'
        nested.mkdir(parents=True)
        d = fixture(ep_root)
        d['project'] = '测试剧'; d['episode'] = 'OP001'
        save_json(ep_root / '制作数据.json', d)
        save_json(nested / '制作数据.json', {'title': 'nested draft missing project/episode/source'})
        entries, issues = catalog(self.root, project='测试剧')
        self.assertEqual(issues, [])
        self.assertTrue(any('OP001' in e['title'] for e in entries))


if __name__ == '__main__':
    unittest.main()
