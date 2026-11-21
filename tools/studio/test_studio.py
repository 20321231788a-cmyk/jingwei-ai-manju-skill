import copy
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

import requests
from model import Studio, load_json, save_json, under
from regeneration import Regenerator
from server import Server, byte_range
from upstream import DEFAULT_PROFILE, validate_profile, validate_submission, RBClient
from exporter import Exporter, ffmpeg_path, probe, run


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.board=self.root/'剧集/EP010/制作数据.json';self.board.parent.mkdir(parents=True)
        self.board.write_text('{"units": []}',encoding='utf-8')
        asset=self.root/'image.png';asset.write_bytes(b'fake-image')
        self.config={'root':self.root,'batch':self.root/'batch','records':self.root/'batch/任务记录','plan_path':self.root/'plan.json'}
        self.config['records'].mkdir(parents=True)
        prompt='first ten seconds\n------\nsecond ten seconds'
        self.item={'request_id':'EP010_S01-reviewed','episode_id':'EP010','episode_dir':'剧集/EP010','unit_id':'EP010_S01',
                   'source_request_ids':['EP010_S01_R01'],'source_board':'剧集/EP010/制作数据.json',
                   'source_board_sha256':hashlib.sha256(self.board.read_bytes()).hexdigest(),'model_request_seconds':20,
                   'adopted_interval':[0,18],'narrative_seconds':18,'preset':'dmad_20','width':1184,'height':672,
                   'prompt':prompt,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                   'bindings':[{'path':'image.png','sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'picture_index':1}]}
        save_json(self.config['plan_path'],{'requests':[self.item],'reviewed_release_ids':[self.item['request_id']]})
        save_json(self.root/'series.json',{'episodes':[{'id':'EP010','title':'第十集','shot_count':1,'current_data':'剧集/EP010/制作数据.json'}]})
        self.s=Studio(self.config);self.s.save_profile({'profile':DEFAULT_PROFILE,'key':'test-secret-only-memory'})

    def tearDown(self):self.tmp.cleanup()

    def regenerate(self,nonce='test-nonce-0001'):
        return self.s.regenerate({'request_ids':[self.item['request_id']],'profile_id':DEFAULT_PROFILE['id'],'nonce':nonce})

    def test_idempotence_and_frozen_upstream_no_secret(self):
        result=self.regenerate();self.assertEqual(result['request_ids'],self.regenerate()['request_ids'])
        changed={**DEFAULT_PROFILE,'base_url':'https://new.example'}
        self.s.save_profile({'profile':changed,'key':'different-key'})
        row=load_json(next(self.s.jobs_dir.glob('*.json')))
        self.assertEqual(row['upstream']['base_url'],DEFAULT_PROFILE['base_url'])
        self.assertEqual(row['source_item']['prompt'],self.item['prompt'])
        for p in self.s.home.rglob('*.json'):
            self.assertNotIn('test-secret-only-memory',p.read_text(encoding='utf-8'))
            self.assertNotIn('different-key',p.read_text(encoding='utf-8'))

    def test_duplicate_active_shot_rejected(self):
        self.regenerate()
        with self.assertRaises(ValueError):self.regenerate('test-nonce-0002')

    def test_card_switch_preserves_old_task_account(self):
        self.regenerate()
        profile_state=self.s.save_profile({'profile':DEFAULT_PROFILE,'key':'new-card-runtime-only'})
        self.assertNotEqual(profile_state['active'],DEFAULT_PROFILE['id'])
        row=load_json(next(self.s.jobs_dir.glob('*.json')))
        self.assertEqual(self.s.keys[self.s.profile_key(row['upstream'])],'test-secret-only-memory')
        self.assertEqual(len(profile_state['profiles']),2)

    def test_new_profile_activates_only_on_restart_without_changing_old(self):
        new={**DEFAULT_PROFILE,'id':'spark-768','name':'Spark 768p','protocol':'sparkcine-v1',
             'video_resolution':'768p','max_concurrency':150}
        state=load_json(self.s.profile_file);state['activate_on_restart']=new
        save_json(self.s.profile_file,state)
        self.assertEqual(self.s.profiles()['active'],DEFAULT_PROFILE['id'])
        restarted=Studio(self.config)
        state=restarted.profiles()
        self.assertEqual(state['active'],'spark-768')
        self.assertEqual(next(p for p in state['profiles'] if p['id']=='spark-768')['video_resolution'],'768p')
        self.assertEqual(next(p for p in state['profiles'] if p['id']==DEFAULT_PROFILE['id'])['protocol'],'rb-v1')
        self.assertNotIn('activate_on_restart',state)

    def test_hash_change_rejected(self):
        self.board.write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):self.regenerate()
        self.assertEqual(len(list(self.s.jobs_dir.glob('*.json'))),0)

    def test_rb_duration_tiers_reject_before_enqueue(self):
        self.item.update(model_request_seconds=9, preset='reference')
        save_json(self.config['plan_path'],{'requests':[self.item],'reviewed_release_ids':[self.item['request_id']]})
        with self.assertRaisesRegex(ValueError,'只支持'):self.regenerate()
        self.assertEqual(list(self.s.jobs_dir.glob('*.json')),[])
        padded={**self.item,'model_request_seconds':15,'preset':'easy_15','width':1344,'height':768,
                'narrative_seconds':9,'adopted_interval':[0,9]}
        validate_submission(DEFAULT_PROFILE,padded)
        with self.assertRaisesRegex(ValueError,'固定画幅'):
            validate_submission(DEFAULT_PROFILE,{**padded,'width':1280,'height':720})
        with self.assertRaisesRegex(ValueError,'对应协议'):
            validate_submission(DEFAULT_PROFILE,{**padded,'required_protocol':'sparkcine-v1'})
        client=RBClient(DEFAULT_PROFILE,'fake-memory-key')
        payload=client.payload(padded,['uploaded-reference'])
        client.close()
        self.assertEqual(payload['preset'],'easy_15')
        self.assertEqual(payload['seconds'],15)
        self.assertEqual(payload['prompt'],padded['prompt'])
        self.assertNotIn('adopted_interval',payload)

    def test_two_episodes_not_allowed(self):
        q=copy.deepcopy(self.item);q.update(request_id='EP011_S01',episode_id='EP011')
        save_json(self.config['plan_path'],{'requests':[self.item,q],'reviewed_release_ids':[self.item['request_id'],q['request_id']]})
        with self.assertRaises(ValueError):self.s.regenerate({'request_ids':[self.item['request_id'],q['request_id']],'profile_id':'rb-default','nonce':'test-nonce-0003'})

    def test_unreviewed_rejected(self):
        save_json(self.config['plan_path'],{'requests':[self.item],'reviewed_release_ids':[]})
        with self.assertRaises(ValueError):self.regenerate()

    def test_selection_approval_requires_explicit_batch_flag(self):
        self.item['ready_for_approval']=True
        save_json(self.config['plan_path'],{'requests':[self.item],'reviewed_release_ids':[]})
        with self.assertRaises(ValueError):self.regenerate()
        result=self.s.regenerate({'request_ids':[self.item['request_id']],'profile_id':DEFAULT_PROFILE['id'],
                                  'nonce':'test-nonce-approved','approve_reviewed_selection':True})
        row=load_json(self.s.jobs_dir/(result['request_ids'][0]+'.json'))
        self.assertEqual(row['user_approval_scope'],'本次选中镜头')
        self.assertEqual(row['source_item']['prompt'],self.item['prompt'])

    def test_restart_does_not_repost_sending(self):
        self.regenerate();p=next(self.s.jobs_dir.glob('*.json'));r=load_json(p);r['submission_state']='sending';save_json(p,r)
        Studio(self.config)
        self.assertEqual(load_json(p)['submission_state'],'uncertain')

    def test_current_progress_excludes_history(self):
        out=self.root/'old.mp4';out.write_bytes(b'0000ftyp'+b'0'*2000)
        save_json(self.config['records']/'old.json',{'request_id':'old','episode_id':'EP010','unit_id':'EP010_S01','job':{'status':'done'},'download':{'path':'old.mp4'}})
        state=self.s.snapshot();self.assertEqual(state['downloaded'],0);self.assertEqual(len(state['videos']),1)

    def test_resubmit_replaces_current_attempt_and_moves_previous_to_history(self):
        out=self.root/'original.mp4';out.write_bytes(b'0000ftyp'+b'0'*2000)
        original={'request_id':self.item['request_id'],'episode_id':'EP010','unit_id':'EP010_S01',
                  'model_request_seconds':20,'created_at':'2020-01-01T00:00:00+00:00',
                  'job':{'id':'original-job','status':'done'},'download':{'path':'original.mp4'}}
        original_path=self.config['records']/'original.json';save_json(original_path,original)
        self.assertEqual(self.s.snapshot()['downloaded'],1)
        rid=self.regenerate()['request_ids'][0]
        # Touching an older completed record must not make it current again.
        original['note']='older download checked';save_json(original_path,original)
        state=self.s.snapshot()
        self.assertEqual(state['downloaded'],0)
        self.assertEqual(state['tasks'][0]['request_id'],rid)
        self.assertEqual(state['tasks'][0]['plan_request_id'],self.item['request_id'])
        self.assertEqual(state['tasks'][0]['state'],'queued')
        self.assertEqual([t['request_id'] for t in state['history']],[self.item['request_id']])
        fake=FakeClient(DEFAULT_PROFILE,'unused');worker=Regenerator(self.s,lambda p,k:fake)
        worker.tick();state=self.s.snapshot()
        self.assertEqual(state['tasks'][0]['state'],'running')
        self.assertEqual(state['tasks'][0]['job_id'],'99')
        fake.remote['99'].update(status='done',has_video=True);worker.tick()
        self.assertEqual(self.s.snapshot()['downloaded'],1)
        self.assertEqual(self.s.snapshot()['tasks'][0]['request_id'],rid)
        newer=self.regenerate('test-nonce-0002')['request_ids'][0]
        # A late update to the previous record must not overtake the new attempt,
        # including resubmissions created within the same second.
        path=self.s.jobs_dir/(rid+'.json');row=load_json(path)
        row['note']='previous download checked again';save_json(path,row);self.s.invalidate()
        state=self.s.snapshot()
        self.assertEqual(state['tasks'][0]['request_id'],newer)
        self.assertEqual(state['tasks'][0]['state'],'queued')
        self.assertEqual(state['downloaded'],0)
        self.assertEqual({t['request_id'] for t in state['history']},{rid,self.item['request_id']})
        self.assertEqual(len(state['videos']),2)
        self.assertEqual(load_json(original_path),original)

    def test_current_and_history_share_submission_state_rules(self):
        rid=self.regenerate()['request_ids'][0]
        path=self.s.jobs_dir/(rid+'.json');row=load_json(path)
        for status in ('waiting_key','capacity_wait','retry_wait','sending','uncertain','rejected'):
            with self.subTest(status=status):
                row.update(submission_state=status,job={'id':'stale','status':'running'})
                save_json(path,row);self.s.invalidate()
                state=self.s.snapshot()
                self.assertEqual(state['tasks'][0]['state'],status)
                self.assertEqual(state['regenerations'][0]['state'],status)

    def test_undated_original_record_cannot_overtake_its_resubmission(self):
        rid=self.regenerate()['request_ids'][0]
        # Older queue formats may omit timestamps. Their later completion write
        # still belongs to the original attempt, rather than the current retry.
        save_json(self.config['records']/'undated.json',{
            'request_id':self.item['request_id'],'episode_id':'EP010','unit_id':'EP010_S01',
            'job':{'id':'old-job','status':'done'}})
        self.s.invalidate();state=self.s.snapshot()
        self.assertEqual(state['tasks'][0]['request_id'],rid)
        self.assertEqual([t['request_id'] for t in state['history']],[self.item['request_id']])

    def test_no_path_traversal(self):
        with self.assertRaises(ValueError):under(self.root,'../elsewhere')
        with self.assertRaises(ValueError):validate_profile({**DEFAULT_PROFILE,'base_url':'https://user:secret@example.com'})
        with self.assertRaises(ValueError):validate_profile({**DEFAULT_PROFILE,'jobs_path':'//evil.example/jobs'})

    def test_protocol_rejects_unknown(self):
        with self.assertRaises(ValueError):validate_profile({**DEFAULT_PROFILE,'protocol':'guess'})

    def test_range(self):
        self.assertEqual(byte_range('bytes=10-19',100),(10,19,True))
        self.assertEqual(byte_range('bytes=-10',100),(90,99,True))
        self.assertEqual(byte_range('bytes=90-',100),(90,99,True))
        for r in ('bytes=100-','bytes=10-2','bytes=0-1,4-5','bytes=-0'):
            with self.assertRaises(ValueError):byte_range(r,100)

    def test_http_origin_and_agent_controls_absent(self):
        server=Server(('127.0.0.1',0),self.s);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            self.assertEqual(requests.get(base+'/api/state').status_code,200)
            self.assertEqual(requests.post(base+'/api/regenerate',json={}).status_code,403)
            headers={'Origin':base,'X-Studio-Token':server.csrf}
            self.assertEqual(requests.post(base+'/api/start',headers=headers,json={}).status_code,404)
            self.assertEqual(requests.get(base+'/api/state',headers={'Host':'evil.example'}).status_code,403)
            self.assertEqual(requests.get(base+'/project/../../plan.json').status_code,404)
        finally:server.shutdown();server.server_close();thread.join()

    def test_rejection_of_invalid_trim(self):
        file=self.root/'sample.mp4';file.write_bytes(b'0000ftyp'+b'x'*2048)
        save_json(self.config['records']/'sample.json',{'request_id':'sample','unit_id':'EP010_S01','episode_id':'EP010','model_request_seconds':20,'download':{'path':'sample.mp4'}})
        vid=self.s.snapshot()['videos'][0]['id']
        for start,end in ((5,4),(-1,4),(0,25),(0,float('nan'))):
            with self.assertRaises(ValueError):self.s.validate_mix({'clips':[{'video_id':vid,'start':start,'end':end}]})

    def test_mock_submit_capacity_poll_and_download(self):
        self.regenerate();fake=FakeClient(DEFAULT_PROFILE,'unused');fake.capacity=True
        worker=Regenerator(self.s,lambda p,k:fake);worker.tick();self.assertEqual(fake.posts,0)
        fake.capacity=False;worker.tick();self.assertEqual(fake.posts,1)
        self.assertEqual(fake.submitted['prompt'].count('\n------\n'),1)
        fake.remote['99'].update(status='done',has_video=True);worker.tick()
        row=load_json(next(self.s.jobs_dir.glob('*.json')))
        self.assertTrue(under(self.root,row['download']['path']).exists());self.assertEqual(fake.posts,1)

    def test_ambiguous_post_never_repeated(self):
        self.regenerate();fake=FakeClient(DEFAULT_PROFILE,'unused');fake.timeout=True
        worker=Regenerator(self.s,lambda p,k:fake);worker.tick();worker.tick()
        self.assertEqual(fake.posts,1)
        row=load_json(next(self.s.jobs_dir.glob('*.json')));self.assertEqual(row['submission_state'],'submitted')

    def test_real_trim_concat_audio_and_silent(self):
        ffmpeg=ffmpeg_path();clips=[]
        for i in range(2):
            path=self.root/f'video{i}.mp4'
            command=[ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i',f'color=c={"red" if i==0 else "blue"}:s=320x180:r=30:d=2']
            if i==0:command+=['-f','lavfi','-i','sine=frequency=440:duration=2','-c:a','aac']
            command+=['-c:v','libx264','-pix_fmt','yuv420p',str(path)];run(command)
            save_json(self.config['records']/f'v{i}.json',{'request_id':f'v{i}','episode_id':'EP010','unit_id':'EP010_S01','model_request_seconds':2,'download':{'path':path.name}})
        for v in self.s.snapshot(force=True)['videos']:clips.append({'video_id':v['id'],'start':.3,'end':1.3})
        exporter=Exporter(self.s);data=exporter.start({'name':'导出验证','clips':clips})
        import time
        deadline=time.monotonic()+60
        while exporter.active and time.monotonic()<deadline:time.sleep(.1)
        result=load_json(self.s.exports_dir/data['id']/'导出状态.json')
        self.assertEqual(result['state'],'done',result)
        meta=probe(self.s.exports_dir/data['id']/'成片.mp4');self.assertTrue(meta['audio']);self.assertAlmostEqual(meta['duration'],2,delta=.2)
        self.assertTrue((self.s.exports_dir/data['id']/'剪辑清单.csv').is_file())


class FakeClient:
    def __init__(self,profile,key):
        self.profile=profile;self.remote={};self.posts=0;self.capacity=False;self.timeout=False
    def close(self):pass
    def jobs(self):return {str(i):{'id':str(i),'status':'running'} for i in range(5)} if self.capacity else copy.deepcopy(self.remote)
    def detail(self,jid):return self.remote[jid]
    def upload(self,path,digest):return 'fake-ref'
    def payload(self,item,refs):return {'preset':item['preset'],'prompt':item['prompt'],'images':refs,'seconds':item['model_request_seconds'],'width':item['width'],'height':item['height']}
    def submit(self,payload):
        self.posts+=1;self.submitted=payload;self.remote['99']={**payload,'id':'99','status':'running'}
        if self.timeout:raise TimeoutError()
        return self.remote['99']
    def download(self,jid,output):
        output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b'0000ftyp'+b'x'*2048)
        return {'size':2056,'sha256':'fake'}


if __name__=='__main__':unittest.main()
