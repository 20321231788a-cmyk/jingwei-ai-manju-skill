"""Documented Wan buyer protocol; no real credentials or paid requests."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from canonical import SKILL, board, plan
from model import Studio, save_json, load_json
from regeneration import Regenerator
from upstream import WanPortalClient, WAN_PROFILE, validate_profile, validate_submission, UpstreamError

sys.path.insert(0, str(SKILL/'scripts'))
from test_build_board import fixture


class FakeWan(WanPortalClient):
    def __init__(self, profile, key):
        super().__init__(profile,key); self.remote={};self.posts=0
    def api(self,method,path,**kw):
        if path=='/api/portal/ride':return {'open':True,'accepting':True}
        if path=='/api/portal/me':return {'remaining':10,'kind':'shot','blocked':False}
        if method=='GET' and path==self.profile['jobs_path']:
            return {'items':list(self.remote.values()),'next':None}
        if method=='GET':return self.remote[path.rsplit('/',1)[1]]
        payload=kw['json'];self.posts+=1
        job={**payload,'status':'boarded','progress':0,'wait':{'phase':'boarding','label':'候车','ahead':3}}
        self.remote[payload['id']]=job;return {'ok':True,'job':job,'remaining':9}
    def upload(self,path,digest):
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        return 'asset-'+digest[:12]
    def download(self,jid,output):
        content=b'\0\0\0\x18ftypisom'+b'0'*2048
        output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(content)
        return {'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}


class WanPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'测试剧/EP01';self.folder.mkdir(parents=True)
        self.data=fixture(self.folder);self.data.update(active_model='wan3',review_status='user_approved')
        g=copy.deepcopy(self.data['units'][0]);g.pop('prompt');g.pop('prompt_zh')
        g.update(id='WAN_G01',model='wan3',duration_s=30,directing_summary='甲问路，乙指向门口。',
                 source_units=['U01','U02'],source_revisions={u['id']:board.source_revision(u) for u in self.data['units']},
                 prompt_text='图1。分镜1（0—30秒）：甲问路。',prompt_language='en',
                 prompt_text_en='图1 provides his identity. Shot 1 (0–30s): He says “门在哪里？”',
                 shots=[{'number':1,'start_s':0,'end_s':30,'description':'甲问路。'}],
                 generation={'protocol':'wan-portal-v1','preset':'reference','width':1920,'height':1080,'narrative_seconds':30,'adopted_interval':[0,30]})
        self.data['generation_groups']=[g]
        self.path=self.folder/'制作数据.json';save_json(self.path,self.data)
        self.studio=Studio({'root':self.root,'canonical':True,'records':self.root/'records'})
        self.profile=validate_profile(WAN_PROFILE);self.studio.save_profile({'profile':self.profile,'key':'fake-card'})

    def tearDown(self):self.temp.cleanup()

    def test_payload_and_stable_id_exact_prompt_original_roles_and_30_seconds(self):
        item,=plan(self.root)['requests'];c=FakeWan(self.profile,'fake-card')
        payload=c.payload(item,['asset-one'],'local-request-001')
        self.assertEqual(payload['id'],c.payload(item,['asset-one'],'local-request-001')['id'])
        self.assertEqual(payload['prompt'],self.data['generation_groups'][0]['prompt_text_en'])
        self.assertEqual((payload['duration'],payload['resolution'],payload['ratio'],payload['copies'],payload['promptExtend']),(30,'1080P','16:9',1,0))
        self.assertEqual(payload['media'],[{'id':'asset-one','kind':'image','token':'图1','role':'ref'}])
        for key,value in [('model_request_seconds',15),('requested_model','MiniMax-H3'),('width',1280)]:
            bad=copy.deepcopy(item);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_submission(self.profile,bad)

    def test_queue_once_then_poll_download_and_card_never_persisted(self):
        item,=self.studio.plan()['requests'];self.assertTrue(item['ready'])
        ids=self.studio.regenerate({'request_ids':[item['request_id']],'profile_id':self.profile['id'],'nonce':'wan-queue-test-001'})['request_ids']
        fake=FakeWan(self.profile,'fake-card');worker=Regenerator(self.studio,lambda p,k:fake)
        worker.tick();self.assertEqual(fake.posts,1)
        worker.tick();self.assertEqual(fake.posts,1)
        job=next(iter(fake.remote.values()));job.update(status='succeeded',wait={'phase':'done','label':'已出片'})
        worker.tick();self.assertEqual(fake.posts,1)
        row=load_json(self.studio.jobs_dir/(ids[0]+'.json'))
        self.assertTrue(row['download']);self.assertEqual(row['source_item']['prompt'],item['prompt'])
        for p in self.root.rglob('*.json'):self.assertNotIn('fake-card',p.read_text(encoding='utf-8'))

    def test_error_detail_redacts_credential_and_closed_ride_never_posts(self):
        c=WanPortalClient(self.profile,'fake-card')
        response=Mock(ok=False,is_redirect=False,status_code=403)
        response.json.return_value={'detail':'额度不足 fake-card WAN-TEST-0000'}
        c.session.request=Mock(return_value=response)
        with self.assertRaises(UpstreamError) as raised:c.api('GET','/api/portal/me')
        self.assertIn('额度不足',str(raised.exception));self.assertNotIn('fake-card',str(raised.exception));self.assertNotIn('WAN-TEST',str(raised.exception))
        item,=plan(self.root)['requests'];f=FakeWan(self.profile,'fake-card');original=f.api
        f.api=lambda method,path,**kw: {'accepting':False} if path=='/api/portal/ride' else original(method,path,**kw)
        with self.assertRaises(UpstreamError):f.submit(f.payload(item,['asset-one'],'same-id'))
        self.assertEqual(f.posts,0)

    def test_upload_sends_original_bytes_without_card_to_signed_storage(self):
        from PIL import Image
        p=self.root/'original.png';Image.new('RGB',(300,300),'white').save(p);raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        c=WanPortalClient(self.profile,'fake-card');c.api=Mock(side_effect=[{'url':'https://storage.example/signed','key':'storage-private-key','contentType':'image/png'},{'id':'asset-one'}])
        response=Mock(ok=True,is_redirect=False);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
        with patch('upstream.requests.put',return_value=response) as put:
            self.assertEqual(c.upload(p,digest),'asset-one')
        self.assertEqual(put.call_args.kwargs['data'],raw)
        self.assertEqual(put.call_args.kwargs['headers'],{'Content-Type':'image/png'})
        self.assertEqual(c.upload(p,digest),'asset-one');self.assertEqual(c.api.call_count,2)

    def test_cancel_requires_upstream_ack_and_keeps_returned_balance(self):
        c=WanPortalClient(self.profile,'fake-card')
        c.api=Mock(return_value={'remaining':10,'job':{'id':'job-one','status':'cancelled','wait':{'phase':'cancelled'}}})
        job,balance=c.cancel('job-one')
        self.assertEqual((job['status'],balance),('cancelled',10))
        c.api.assert_called_once_with('DELETE','/api/portal/jobs/job-one')
        c.api=Mock(side_effect=UpstreamError(409,'已经发车，不能取消'))
        with self.assertRaises(UpstreamError):c.cancel('job-one')


if __name__=='__main__':unittest.main()
