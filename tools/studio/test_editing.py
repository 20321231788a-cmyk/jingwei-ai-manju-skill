import copy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests
from canonical import SKILL, catalog
from editing import EditConflict, save_draft
from model import Studio, load_json, save_json
from server import Server
from upstream import DEFAULT_PROFILE, UpstreamError

sys.path.insert(0, str(SKILL/'scripts'))
from test_build_board import fixture


class EditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        folder = self.root/'测试/EP001'; folder.mkdir(parents=True)
        self.path = folder/'制作数据.json'
        data = fixture(folder); data['review_status'] = 'reviewed'
        save_json(self.path, data)
        self.s = Studio({'root':self.root, 'canonical':True, 'records':self.root/'records'})
        self.s.save_profile({'profile':DEFAULT_PROFILE, 'key':'fake-memory-secret'})
        self.eid = catalog(self.root)[0][0]['id']

    def tearDown(self): self.temp.cleanup()

    def edit(self, index=0, **changes):
        unit = self.s.episode(self.eid)['units'][index]
        return save_draft(self.s, {'episode_id':self.eid, 'unit_id':unit['id'],
                                  'base_revision':unit['edit_revision'], 'changes':changes})

    def test_pending_blocks_only_edited_unit_and_preserves_committed_content(self):
        original = copy.deepcopy(load_json(self.path)['units'][0])
        self.edit(action='林昊抬头，怒视火外两人。', duration_s=9, dialogue=['林昊：我愿意。'])
        units = load_json(self.path)['units']
        self.assertEqual({k:v for k,v in units[0].items() if k!='editor_draft'}, original)
        plan = self.s.plan()['requests']
        self.assertTrue(plan[0]['pending_sync'])
        self.assertFalse(plan[0]['ready_for_approval'])
        self.assertTrue(plan[1]['ready_for_approval'])
        self.assertEqual(plan[0]['model_request_seconds'],9)
        with self.assertRaisesRegex(ValueError,'尚未同步'):
            self.s.regenerate({'request_ids':[plan[0]['request_id']], 'profile_id':DEFAULT_PROFILE['id'],
                               'nonce':'editing-approval-0001','approve_reviewed_selection':True})
        self.assertEqual(list(self.s.jobs_dir.glob('*.json')),[])

    def test_conflict_rejects_same_unit_but_allows_other_unit(self):
        old = self.s.episode(self.eid)['units'][0]
        self.edit(title='新标题')
        with self.assertRaises(EditConflict):
            save_draft(self.s, {'episode_id':self.eid,'unit_id':old['id'],
                               'base_revision':old['edit_revision'],'changes':{'title':'覆盖'}})
        self.edit(1, title='另一个镜头')
        self.assertEqual(load_json(self.path)['units'][0]['editor_draft']['values']['title'],'新标题')
        self.assertEqual(load_json(self.path)['units'][1]['editor_draft']['values']['title'],'另一个镜头')

    def test_validation_and_discard(self):
        for changes in ({'duration_s':True},{'duration_s':3},{'duration_s':16},
                        {'prompt':{}},{'references':[]},{'dialogue':'错误格式'},{'title':' '}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.edit(**changes)
        result = self.edit(camera='低机位缓慢推进')
        u = result['unit']
        result = save_draft(self.s, {'episode_id':self.eid,'unit_id':u['id'],
                                    'base_revision':u['edit_revision'],'discard':True})
        self.assertFalse(result['unit']['pending_sync'])
        self.assertTrue(self.s.plan()['requests'][0]['ready_for_approval'])

    def test_original_board_is_editable_without_changing_exports_or_committed_prompt(self):
        from canonical import html
        before = load_json(self.path)['units'][0]['prompt']
        self.edit(chinese_description='[Shot 1] 点击原镜头正文后修改的完整中文。')
        unit = self.s.episode(self.eid)['units'][0]
        self.assertIn('点击原镜头正文',unit['editable_values']['chinese_description'])
        self.assertEqual(load_json(self.path)['units'][0]['prompt'], before)
        page = html(self.root,self.eid)
        self.assertIn('board-editor.js',page)
        self.assertIn('board-editor-data',page)
        self.assertIn('H3镜头（中文）',page)
        self.assertIn('class="frames"',page)
        self.assertNotIn('unit-monitor',page)

    def test_frozen_history_unchanged_after_edit(self):
        # Use an actual RB-supported tier when testing immutable paid snapshots.
        data=load_json(self.path)
        data['units'][0]['duration_s'] = 15
        data['units'][0]['generation'] = dict(protocol='rb-v1',preset='easy_15',width=1344,height=768,
                                                  narrative_seconds=12,adopted_interval=[0,12])
        save_json(self.path,data)
        plans=self.s.plan()['requests']
        self.s.regenerate({'request_ids':[plans[0]['request_id']], 'profile_id':DEFAULT_PROFILE['id'],
                           'nonce':'editing-freeze-0001','approve_reviewed_selection':True})
        frozen={p:p.read_bytes() for p in self.s.jobs_dir.glob('*.json')}
        self.edit(title='只改未来的镜头')
        self.assertEqual({p:p.read_bytes() for p in frozen},frozen)

    def test_http_csrf_and_conflict(self):
        server=Server(('127.0.0.1',0),self.s)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        unit=self.s.episode(self.eid)['units'][0]
        body={'episode_id':self.eid,'unit_id':unit['id'],'base_revision':unit['edit_revision'],
              'changes':{'title':'浏览器保存'}}
        try:
            self.assertEqual(requests.post(base+'/api/unit-draft',json=body).status_code,403)
            headers={'Origin':base,'X-Studio-Token':server.csrf}
            self.assertEqual(requests.post(base+'/api/unit-draft',json=body,headers=headers).status_code,200)
            response=requests.post(base+'/api/unit-draft',json=body,headers=headers)
            self.assertEqual(response.status_code,409)
            self.assertTrue(response.json()['conflict'])
            self.assertEqual(requests.get(base+'/editor.js').status_code,200)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_profile_edit_reuses_key_only_for_same_destination(self):
        original=copy.deepcopy(DEFAULT_PROFILE)
        updated={**original,'name':'修改名称'}
        state=self.s.save_profile({'profile':updated})
        active=next(p for p in state['profiles'] if p['id']==state['active'])
        self.assertTrue(active['credential_ready'])
        self.assertTrue(next(p for p in state['profiles'] if p['id']==original['id'])['credential_ready'])
        active['base_url']='https://other.example'
        state=self.s.save_profile({'profile':active})
        self.assertFalse(next(p for p in state['profiles'] if p['id']==state['active'])['credential_ready'])

    def test_connection_test_queries_only_and_does_not_store_key(self):
        before=self.s.profile_file.read_bytes()
        client=Mock();client.jobs.return_value=[]
        factory=Mock(return_value=client)
        result=self.s.test_profile({'profile':DEFAULT_PROFILE,'key':'one-off-test-secret'},factory)
        self.assertTrue(result['ok']);client.jobs.assert_called_once_with();client.close.assert_called_once_with()
        self.assertEqual(client.method_calls,[unittest.mock.call.jobs(),unittest.mock.call.close()])
        self.assertEqual(self.s.profile_file.read_bytes(),before)
        self.assertNotIn('one-off-test-secret',str(self.s.keys))
        client.jobs.side_effect=UpstreamError(401)
        with self.assertRaisesRegex(ValueError,'HTTP 401'):
            self.s.test_profile({'profile':DEFAULT_PROFILE},factory)
        client.jobs.side_effect=RuntimeError('sensitive one-off-test-secret')
        with self.assertRaises(ValueError) as context:
            self.s.test_profile({'profile':DEFAULT_PROFILE},factory)
        self.assertNotIn('secret',str(context.exception))


if __name__=='__main__': unittest.main()
