"""Wan storyboard editing is local and cannot fall through to paid H3 requests."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

from canonical import SKILL, board, catalog, html, plan
from editing import save_draft
from model import Studio, load_json, save_json
from upstream import DEFAULT_PROFILE

sys.path.insert(0, str(SKILL / 'scripts'))
from test_build_board import fixture


class WanStoryboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / '测试剧/EP01'
        self.folder.mkdir(parents=True)
        self.data = fixture(self.folder)
        self.data['review_status'] = 'user_approved'
        self.data['active_model'] = 'wan3'
        group = copy.deepcopy(self.data['units'][0])
        group.pop('prompt'); group.pop('prompt_zh')
        group.update(id='WAN_G01', model='wan3', duration_s=30,
                     directing_summary='甲问路，乙在门边指方向。',
                     prompt_text='图1提供甲的身份。\n分镜1（0—30秒）：甲问路，乙指向门口。',
                     source_units=['U01', 'U02'],
                     source_revisions={u['id']: board.source_revision(u) for u in self.data['units']},
                     shots=[dict(number=1, start_s=0, end_s=30, description='甲问路，乙指向门口。')])
        self.data['generation_groups'] = [group]
        self.path = self.folder / '制作数据.json'
        save_json(self.path, self.data)
        self.studio = Studio({'root': self.root, 'canonical': True, 'records': self.root / 'records'})
        self.eid = catalog(self.root)[0][0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def test_wan_view_preserves_source_and_cannot_submit_as_h3(self):
        self.assertEqual(board.validate(self.data, self.folder, True), ([], []))
        q, = plan(self.root)['requests']
        self.assertEqual((q['model_request_seconds'], q['requested_model']), (30, 'wan3'))
        self.assertEqual(q['prompt'], self.data['generation_groups'][0]['prompt_text'])
        self.assertFalse(q['ready'])
        self.assertFalse(q['ready_for_approval'])
        self.studio.save_profile({'profile': DEFAULT_PROFILE, 'key': 'fake-test-key'})
        with self.assertRaises(ValueError):
            self.studio.regenerate({'request_ids': [q['request_id']], 'nonce': 'wan-blocked-001', 'profile_id': DEFAULT_PROFILE['id']})
        self.assertFalse(list(self.studio.jobs_dir.glob('*.json')))
        page = html(self.root, self.eid)
        self.assertIn('Wan3分镜（中文）', page)
        self.assertIn('完整Wan3提示词', page)
        self.assertIn('原分镜与独立片头对照', page)
        self.assertEqual(load_json(self.path)['units'], self.data['units'])

    def test_draft_saves_to_group_without_altering_source_or_compiled_prompt(self):
        u, = self.studio.episode(self.eid)['units']
        result = save_draft(self.studio, dict(episode_id=self.eid, unit_id=u['id'],
                            base_revision=u['edit_revision'], changes={'chinese_description': '图1。分镜1（0—30秒）：修改后的对白与动作。'}))
        saved = load_json(self.path)
        self.assertEqual(saved['units'], self.data['units'])
        self.assertTrue(result['unit']['pending_sync'])
        self.assertEqual(saved['generation_groups'][0]['prompt_text'], self.data['generation_groups'][0]['prompt_text'])
        self.assertIn('修改后的对白', saved['generation_groups'][0]['editor_draft']['values']['chinese_description'])
        self.assertFalse(plan(self.root)['requests'][0]['ready'])
        with self.assertRaises(ValueError):
            save_draft(self.studio, dict(episode_id=self.eid, unit_id=result['unit']['id'],
                       base_revision=result['unit']['edit_revision'], changes={'duration_s': 15}))

    def test_native_wan_without_legacy_h3_is_discovered(self):
        self.data['units'] = []
        group = self.data['generation_groups'][0]
        group.pop('source_units')
        group.pop('source_revisions')
        save_json(self.path, self.data)
        self.assertEqual(board.validate(self.data, self.folder, True), ([], []))
        entry, = catalog(self.root)[0]
        self.assertEqual(entry['shot_count'], 1)
        request, = plan(self.root)['requests']
        self.assertEqual(request['prompt'], group['prompt_text'])
        self.assertEqual(request['requested_model'], 'wan3')
        group['shots'][0]['end_s'] = 29
        self.assertTrue(board.validate(self.data, self.folder, True)[0])
        self.data.pop('active_model')
        self.assertIn('缺少分镜单元', board.validate(self.data, self.folder, True)[0])

    def test_gaps_stale_sources_and_foreign_references_are_rejected(self):
        for mutation in ('duration', 'gap', 'source', 'picture', 'h3'):
            data = copy.deepcopy(self.data)
            group = data['generation_groups'][0]
            if mutation == 'duration': group['duration_s'] = 29
            if mutation == 'gap': group['shots'][0]['start_s'] = 1
            if mutation == 'source': data['units'][0]['action'] = '来源已更新'
            if mutation == 'picture': group['prompt_text'] += '图2'
            if mutation == 'h3': group['prompt_text'] += '<Picture 1>'
            with self.subTest(mutation=mutation):
                self.assertTrue(board.validate(data, self.folder, True)[0])

    def test_requested_english_keeps_chinese_editable_and_uses_wan_format(self):
        group = self.data['generation_groups'][0]
        group.update(prompt_language='en', prompt_text_en='图1 defines the identity.\nShot 1 (0–30s): He asks in Mandarin, “门在哪里？”')
        save_json(self.path, self.data)
        self.assertEqual(board.validate(self.data, self.folder, True), ([], []))
        q, = plan(self.root)['requests']
        self.assertEqual(q['prompt'], group['prompt_text_en'])
        u, = self.studio.episode(self.eid)['units']
        self.assertEqual(u['editable_values']['chinese_description'], group['prompt_text'])
        self.assertIn('完整Wan3英文提示词', html(self.root, self.eid))
        group.pop('prompt_text_en')
        self.assertTrue(board.validate(self.data, self.folder, True)[0])


if __name__ == '__main__':
    unittest.main()
