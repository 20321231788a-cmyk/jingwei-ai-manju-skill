import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from upstream import DEFAULT_PROFILE, SparkCineClient, matches, validate_profile


PROFILE = {**DEFAULT_PROFILE, 'id':'sparkcine-test', 'name':'SparkCine',
           'base_url':'https://hi.hi.run', 'protocol':'sparkcine-v1',
           'jobs_path':'/api/open/v1/generations', 'presign_path':'/api/open/v1/uploads',
           'commit_path':'/api/open/v1/uploads/{id}/complete',
           'video_path':'/api/open/v1/generations/{id}', 'max_concurrency':150,
           'preset_map':{**DEFAULT_PROFILE['preset_map'],'reference':'h3-video-flex'}}


class SparkCineTests(unittest.TestCase):
    def setUp(self):
        self.client=SparkCineClient(PROFILE,'test-key')
        self.item={'preset':'reference','prompt':'subject_definitions:\n原始提示词',
                   'width':1280,'height':720,'model_request_seconds':14,'unit_id':'EP001_U01'}

    def tearDown(self):
        self.client.close()

    def test_model_input_order_and_original_prompt_with_idempotency(self):
        payload=self.client.payload(self.item,['asset-a','asset-b'],'selected-request-123456')
        self.assertEqual(payload['prompt'],self.item['prompt'])
        self.assertIs(payload['optimize_prompt'],False)
        self.assertEqual(payload['model'],'h3-video-flex')
        self.assertEqual(payload['inputs'],[{'asset_id':'asset-a','role':'reference_image'},
                                            {'asset_id':'asset-b','role':'reference_image'}])
        self.assertEqual(payload['parameters'],{'duration':14,'resolution':'720p','aspect_ratio':'16:9','generate_audio':True})
        with patch.object(self.client,'api',return_value={'id':'job-1','status':'queued'}) as api:
            self.assertEqual(self.client.submit(payload)['id'],'job-1')
            key=api.call_args.kwargs['headers']['Idempotency-Key']
            self.client.submit(payload)
            self.assertEqual(key,api.call_args.kwargs['headers']['Idempotency-Key'])
            self.assertGreaterEqual(len(key),16)

    def test_explicit_profile_limit_is_scoped_to_sparkcine(self):
        self.assertEqual(validate_profile(PROFILE)['max_concurrency'],150)
        with self.assertRaises(ValueError):validate_profile({**DEFAULT_PROFILE,'max_concurrency':150})
        with self.assertRaises(ValueError):self.client.payload({**self.item,'model_request_seconds':20},[],'request')

    def test_mixed_reference_roles_and_video_upload_preserve_original_inputs(self):
        item={**self.item,'bindings':[{'picture_index':1}, {'video_index':1,'role':'reference_video'}, {'picture_index':2}],
              'mute_reference_video':True}
        payload=self.client.payload(item,['face','motion','costume'],'mixed-reference-123')
        self.assertEqual([x['role'] for x in payload['inputs']],['reference_image','reference_video','reference_image'])
        self.assertEqual([x['asset_id'] for x in payload['inputs']],['face','motion','costume'])
        self.assertIs(payload['parameters']['mute_reference_video'],True)
        self.assertIs(payload['optimize_prompt'],False)
        self.assertEqual(payload['prompt'],item['prompt'])
        with self.assertRaises(ValueError):self.client.payload(item,['face'],'bad-length')
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'motion.mp4';video.write_bytes(b'0000ftyp'+b'x'*30)
            digest=hashlib.sha256(video.read_bytes()).hexdigest()
            with patch.object(self.client,'api',return_value={'asset_id':'motion','reused':True,'state':'READY'}) as api:
                self.assertEqual(self.client.upload(video,digest),'motion')
                self.assertEqual(api.call_args.kwargs['json']['content_type'],'video/mp4')

    def test_768p_is_frozen_per_profile_and_legacy_stays_720p(self):
        self.assertNotIn('video_resolution',validate_profile(PROFILE))
        profile768={**PROFILE,'video_resolution':'768p'}
        client768=SparkCineClient(profile768,'test-key')
        try:
            payload=client768.payload(self.item,['asset-a'],'selected-request-123456')
            self.assertEqual(payload['parameters']['resolution'],'768p')
            self.assertEqual(payload['parameters']['aspect_ratio'],'16:9')
            self.assertIs(payload['optimize_prompt'],False)
            self.assertEqual(payload['prompt'],self.item['prompt'])
            job={'id':'job','status':'generating','model':'h3-video-flex','prompt':self.item['prompt'],
                 'parameters':{'duration':14,'resolution':'768p','aspect_ratio':'16:9'}}
            normalized=client768.normalize(job)
            self.assertTrue(matches(self.item,normalized,profile768))
            self.assertFalse(matches(self.item,normalized,PROFILE))
        finally:client768.close()
        with self.assertRaises(ValueError):validate_profile({**PROFILE,'video_resolution':'invalid'})

    def test_1080p_remains_an_explicit_profile_choice(self):
        p={**PROFILE,'id':'spark-1080','video_resolution':'1080p'}
        client=SparkCineClient(p,'test-key')
        try:
            payload=client.payload({**self.item,'model_request_seconds':6},['asset-a'],'1080-reference')
            self.assertEqual(payload['parameters']['resolution'],'1080p')
            self.assertEqual(payload['parameters']['duration'],6)
            self.assertIs(payload['optimize_prompt'],False)
            normalized=client.normalize({'id':'1080','status':'queued','model':'h3-video-flex','prompt':self.item['prompt'],
                'parameters':{'duration':6,'resolution':'1080p','aspect_ratio':'16:9'}})
            self.assertEqual((normalized['width'],normalized['height']),(1920,1080))
            self.assertTrue(matches({**self.item,'model_request_seconds':6},normalized,p))
        finally:client.close()

    def test_upload_reuses_or_completes_without_forwarding_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'reference.png'; image.write_bytes(b'image bytes')
            digest=hashlib.sha256(image.read_bytes()).hexdigest()
            with patch.object(self.client,'api',return_value={'asset_id':'old','reused':True,'state':'READY'}):
                self.assertEqual(self.client.upload(image,digest),'old')
            self.client.images.clear()
            response=requests.Response();response.status_code=200;response._content=b'';response._content_consumed=True
            with patch.object(self.client,'api',side_effect=[{'asset_id':'new','reused':False,'state':'PENDING',
                    'upload':{'method':'PUT','url':'https://storage.example/signed','headers':{'Content-Type':'image/png'}}},{'state':'READY'}]) as api, \
                 patch('upstream.requests.put',return_value=response) as put:
                self.assertEqual(self.client.upload(image,digest),'new')
                self.assertNotIn('Authorization',put.call_args.kwargs['headers'])
                self.assertEqual(api.call_args.args[1],'/api/open/v1/uploads/new/complete')

    def test_paginated_job_list_and_reconciliation_fields(self):
        job={'id':'a','status':'generating','model':'h3-video-flex','prompt':self.item['prompt'],
             'parameters':{'duration':14,'resolution':'720p','aspect_ratio':'16:9'}}
        with patch.object(self.client,'api',side_effect=[{'data':[job],'has_more':True,'next_cursor':'cursor'},
                {'data':[{'id':'b','status':'succeeded','output_asset_ids':['video']}],'has_more':False}]) as api:
            jobs=self.client.jobs()
            self.assertEqual(jobs['a']['status'],'running')
            self.assertEqual(jobs['b']['status'],'done')
            self.assertTrue(jobs['b']['has_video'])
            self.assertEqual(api.call_args.kwargs['params']['cursor'],'cursor')
            self.assertTrue(matches(self.item,jobs['a'],PROFILE))

    def test_download_checks_size_and_does_not_send_key(self):
        data=b'0000ftyp'+b'x'*2048
        response=requests.Response();response.status_code=200;response._content=data;response._content_consumed=True
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(self.client,'detail',return_value={'outputs':[{'media_type':'video','download_url':'https://storage.example/signed','byte_length':len(data)}]}), \
             patch('upstream.requests.get',return_value=response) as get:
            out=Path(tmp)/'video.mp4';result=self.client.download('job',out)
            self.assertEqual(out.read_bytes(),data)
            self.assertEqual(result['size'],len(data))
            self.assertNotIn('headers',get.call_args.kwargs)


if __name__=='__main__':unittest.main()
