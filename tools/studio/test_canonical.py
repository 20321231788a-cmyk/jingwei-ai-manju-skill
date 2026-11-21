import copy
import json
import sys
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import requests
from canonical import SKILL, board, catalog, plan
from model import Studio, save_json, load_json
from regeneration import Regenerator
from server import Server
from upstream import DEFAULT_PROFILE
from test_studio import FakeClient
sys.path.insert(0, str(SKILL/'scripts'))
from test_build_board import fixture


class CanonicalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root/'测试剧/EP001';self.directory.mkdir(parents=True)
        self.data = fixture(self.directory)
        self.data['units'][0]['duration_s'] = 15
        self.data['units'][0]['generation'] = dict(protocol='rb-v1', preset='easy_15', width=1344, height=768,
                                                  narrative_seconds=12, adopted_interval=[0,12])
        self.data['review_status'] = 'user_approved'
        self.source = self.directory/'制作数据.json'
        save_json(self.source, self.data)
        self.studio = Studio({'root':self.root, 'canonical':True, 'records':self.root/'records'})
        self.studio.save_profile({'profile':DEFAULT_PROFILE,'key':'fake-key'})

    def tearDown(self):self.temp.cleanup()

    def enqueue(self, nonce='test-canonical-001'):
        items = self.studio.plan()['requests']
        return self.studio.regenerate({'request_ids':[q['request_id'] for q in items], 'nonce':nonce, 'profile_id':DEFAULT_PROFILE['id']})

    def test_exact_prompt_duration_and_latest_progress(self):
        items = plan(self.root)['requests']
        self.assertEqual([q['model_request_seconds'] for q in items], [15,4])
        self.assertEqual(items[0]['adopted_interval'], [0,12])
        self.assertEqual(items[0]['narrative_seconds'], 12)
        self.assertEqual((items[0]['preset'],items[0]['width'],items[0]['height']), ('easy_15',1344,768))
        self.assertTrue(all(q['ready'] for q in items))
        self.assertEqual(items[0]['prompt'], '\n\n'.join(f'{field}:\n{self.data["units"][0]["prompt"][field]}' for field in board.FIELDS))
        self.enqueue()
        fake = FakeClient(DEFAULT_PROFILE,'unused')
        # Unique simulated job ids per submitted unit.
        original = fake.submit
        def submit(payload):
            job = original(payload);jid=str(fake.posts)
            fake.remote.pop('99');fake.remote[jid]={**job,'id':jid};return fake.remote[jid]
        fake.submit=submit
        worker = Regenerator(self.studio,lambda p,k:fake);worker.tick()
        self.assertEqual(fake.posts,2)
        for job in fake.remote.values():job.update(status='done',has_video=True)
        worker.tick()
        self.assertEqual(self.studio.snapshot(force=True)['downloaded'],2)
        self.assertFalse((self.root/'series.json').exists())
        self.assertEqual(len(list(self.root.rglob('制作数据.json'))),1)

    def test_review_not_approval_and_revision_rejects_old_selection(self):
        old_ids=[q['request_id'] for q in plan(self.root)['requests']]
        self.data['review_status']='reviewed';save_json(self.source,self.data)
        self.assertFalse(plan(self.root)['reviewed_release_ids'])
        with self.assertRaises(ValueError):self.enqueue()
        with self.assertRaises(ValueError):self.studio.regenerate({'request_ids':old_ids,'nonce':'test-old-selection','profile_id':DEFAULT_PROFILE['id']})

    def test_revision_keeps_current_attempt_and_blocks_duplicate_active_shot(self):
        previous=self.enqueue()['request_ids']
        frozen={p:p.read_bytes() for p in self.studio.jobs_dir.glob('*.json')}
        self.data['title']='修订后的标题';save_json(self.source,self.data)
        self.studio.invalidate();state=self.studio.snapshot()
        self.assertEqual({t['request_id'] for t in state['tasks']},set(previous))
        self.assertFalse(state['history'])
        self.assertEqual({t['plan_request_id'] for t in state['tasks']},
                         {q['request_id'] for q in self.studio.plan()['requests']})
        with self.assertRaisesRegex(ValueError,'在途'):self.enqueue('test-new-revision')
        self.assertEqual({p:p.read_bytes() for p in frozen},frozen)

    def test_cross_project_and_missing_or_external_assets(self):
        other=self.root/'另一部剧/EP001';other.mkdir(parents=True)
        data=fixture(other);save_json(other/'制作数据.json',data)
        entries,_=catalog(self.root);self.assertEqual(len({e['id'] for e in entries}),2)
        (self.directory/'人物图.png').unlink()
        self.assertFalse(plan(self.root)['reviewed_release_ids'])

    def test_http_board_assets_and_no_private_files(self):
        eid=catalog(self.root)[0][0]['id']
        server=Server(('127.0.0.1',0),self.studio)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            response=requests.get(base+'/board/'+eid)
            self.assertEqual(response.status_code,200)
            self.assertIn('复制完整提示词',response.text)
            self.assertIn('H3镜头（中文）',response.text)
            self.assertIn('切到听者近景',response.text)
            self.assertIn('&lt;Picture 1&gt;',response.text)
            self.assertEqual(requests.get(base+'/project/测试剧/EP001/人物图.png').status_code,200)
            img_resp=requests.get(base+'/project/测试剧/EP001/人物图.png')
            self.assertEqual(img_resp.status_code,200);self.assertIn('ETag',img_resp.headers)
            self.assertEqual(requests.get(base+'/project/测试剧/EP001/人物图.png',headers={'If-None-Match':img_resp.headers['ETag']}).status_code,304)
            self.assertEqual(requests.get(base+'/project/测试剧/EP001/制作数据.json').status_code,400)
            self.assertEqual(requests.get(base+'/project/制作资料/制作看板/上游配置.json').status_code,400)
            run=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).with_name('submit.py')),
                                '--url',base,'--episode',eid,'--units','U01'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('仅预览',run.stdout)
            self.assertEqual(list(self.studio.jobs_dir.glob('*.json')),[])
        finally:server.shutdown();server.server_close();thread.join()

    def test_empty_workspace(self):
        self.source.unlink()
        self.assertEqual(self.studio.snapshot(force=True)['episodes'],[])
        self.assertEqual(self.studio.snapshot()['total'],0)

    def test_mixed_references_have_independent_numbers_and_unsupported_profile_is_blocked(self):
        (self.directory/'动作.mp4').write_bytes(b'0000ftyp'+b'x'*30)
        self.data['references'].append(dict(id='V01',type='video_reference',path='动作.mp4',purpose='动作与运镜参考',verified=True))
        unit=self.data['units'][0];unit['references']=['V01','C01'];unit['mute_reference_video']=True
        unit['prompt']['subject_definitions']+='\n<Video 1> provides camera movement.'
        save_json(self.source,self.data)
        item=plan(self.root)['requests'][0]
        self.assertTrue(item['ready'])
        self.assertEqual(item['bindings'][0]['video_index'],1)
        self.assertEqual(item['bindings'][0]['role'],'reference_video')
        self.assertEqual(item['bindings'][1]['picture_index'],1)
        self.assertIs(item['mute_reference_video'],True)
        html=board.render(self.data,self.directory,self.directory/'打开看板.html',[])
        self.assertIn('<video controls',html)
        self.assertIn('Video 1',html)
        with self.assertRaisesRegex(ValueError,'视频参考'):self.enqueue('mixed-unsupported-profile')
        self.assertEqual(list(self.studio.jobs_dir.glob('*.json')),[])
        unit['prompt']['summary']+=' <Picture 2>'
        self.assertTrue(board.validate(self.data,self.directory,True)[0])

    def test_single_project_studio_isolation(self):
        from canonical import discover_projects
        other=self.root/'另一部剧/EP001';other.mkdir(parents=True)
        other_data=fixture(other);other_data.update(project='另一部剧',episode='EP001',title='另一部剧第一集',review_status='user_approved')
        save_json(other/'制作数据.json',other_data)
        discovered=[p['name'] for p in discover_projects(self.root)]
        self.assertEqual(set(discovered),{'测试剧','另一部剧'})
        proj_home=self.root/'另一部剧/制作资料/制作看板'
        scoped=Studio({'root':self.root,'canonical':True,'project':'另一部剧','home':proj_home,'records':proj_home/'历史任务'})
        snap=scoped.snapshot(force=True)
        self.assertEqual(len(snap['episodes']),1)
        self.assertEqual(snap['episodes'][0]['title'],'另一部剧 · EP001 · 另一部剧第一集')
        self.assertEqual(scoped.home,proj_home.resolve())
        server=Server(('127.0.0.1',0),scoped)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            boot=requests.get(base+'/api/bootstrap').json()
            self.assertEqual(boot['project'],'另一部剧')
            self.assertEqual(requests.get(base+'/project/另一部剧/EP001/人物图.png').status_code,200)
            self.assertEqual(requests.get(base+'/project/测试剧/EP001/人物图.png').status_code,400)
        finally:server.shutdown();server.server_close();thread.join()

    def test_launch_port_probe_is_fast(self):
        import time
        from launch import find_target_port, project_port
        t0=time.monotonic()
        port=find_target_port('我在都市做柳家出马仙')
        self.assertLess(time.monotonic()-t0, 0.5)
        self.assertGreaterEqual(port, 8766)
        self.assertEqual(project_port(None), 8766)


if __name__=='__main__':unittest.main()
