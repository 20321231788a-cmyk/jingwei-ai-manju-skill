"""Only processes explicit studio resubmissions. Never starts/stops the agent queue."""
import threading
import time
import hashlib
from urllib.parse import urlsplit

from model import load_json, save_json, stamp, under
from upstream import RBClient, SparkCineClient, UpstreamError, matches, client_type
from submission_priority import submission_turn, priority_head, publish_ready, other_upstream_active


def brief(job):
    # Provider payloads may contain signed URLs; persist only safe, useful fields.
    return {k: job[k] for k in ('id', 'status', 'provider_status', 'error_code', 'has_video', 'progress', 'created_at', 'updated_at', 'wait_phase', 'wait_label', 'queue_ahead', 'eta_depart_at', 'error_message') if k in job}


class Regenerator:
    def __init__(self, studio, client_factory=None):
        self.studio = studio; self.clients = {}; self.client_factory=client_factory
        self.stop = threading.Event()
        self.pause_priority_until = 0

    def publish_readiness(self):
        with self.studio.lock:
            tokens=list(self.studio.keys) if time.time()>=self.pause_priority_until and not self.stop.is_set() else []
            if tokens or (self.studio.home/'优先队列服务.json').exists():
                publish_ready(self.studio.root,tokens,home_dir=self.studio.home)

    def heartbeat(self):
        while not self.stop.is_set():
            try:self.publish_readiness()
            except OSError:pass
            self.stop.wait(5)

    def run(self):
        threading.Thread(target=self.heartbeat,daemon=True).start()
        while not self.stop.is_set():
            try:
                self.tick()
                self.pause_priority_until=0
                self.studio.health={'checked_at':stamp(),'error':None}
            except Exception as error:
                # Never echo upstream messages, credentials or signed URLs.
                self.pause_priority_until=time.time()+30
                self.publish_readiness()
                self.studio.health={'checked_at':stamp(),'error':type(error).__name__+'：本地重提服务稍后再试'}
            self.stop.wait(15)

    def persist(self,path,row):
        save_json(path,row); self.studio.invalidate()

    def reconcile(self,client,row,jobs):
        if row['upstream']['protocol'] == 'doubao-canvas-v1':
            checkpoint = row.get('prepared_submission') or {}
            job = jobs.get(checkpoint.get('id'))
            if job and job.get('accepted'):
                row['job'] = brief(job); row['submission_state'] = 'submitted'
                row['note'] = '已按生成前冻结的画布节点恢复任务，未重新生成。'
            else:
                row['note'] = '原节点尚未确认受理，继续核对，不重发生成请求。'
            return
        candidates=[]
        baseline=set(row.get('baseline_job_ids', []))
        for jid,job in jobs.items():
            if jid in baseline:
                continue
            if matches(row['source_item'],client.detail(jid),row['upstream']):
                candidates.append(job)
        if len(candidates)==1:
            row['job']=brief(candidates[0]); row['submission_state']='submitted'
            row['note']='已通过完整提示词与参数唯一匹配恢复任务。'
        else:
            row['note']='提交结果待核对；不自动重发，请交由 agent 核对。'

    def tick(self):
        self.publish_readiness()
        groups={}
        for path in sorted(self.studio.jobs_dir.glob('*.json')):
            row=load_json(path)
            if row.get('download') or row['submission_state'] in ('rejected','failed','cancelled'):
                continue
            if (row.get('job') or {}).get('status') in ('failed','cancelled'):
                continue
            groups.setdefault(self.studio.profile_key(row['upstream']),[]).append((path,row))
        for token,rows in groups.items():
            key=self.studio.keys.get(token)
            if not key:
                for path,row in rows:
                    if row['submission_state'] in ('queued','capacity_wait','waiting_key'):
                        row['submission_state']='waiting_key';row['note']='服务重启后须重新输入此任务原接口的卡密。';self.persist(path,row)
                continue
            credential_hash=hashlib.sha256(key.encode()).hexdigest()
            cached=self.clients.get(token)
            if cached is not None and getattr(cached,'credential_hash',None)!=credential_hash:
                cached.close();self.clients.pop(token)
            if token not in self.clients:
                profile=rows[0][1]['upstream']
                factory=self.client_factory or client_type(profile)
                self.clients[token]=factory(profile,key)
                self.clients[token].credential_hash=credential_hash
            client=self.clients[token]
            if hasattr(client, 'track'):
                client.track([row for _, row in rows])
            try:
                jobs=client.jobs()
            except UpstreamError as error:
                for path,row in rows:
                    row['note']=str(error)+'；请检查原上游配置及卡密。'; self.persist(path,row)
                if error.status in (401,403):
                    self.studio.keys.pop(token,None); self.clients.pop(token).close()
                continue
            uncertain=False
            for path,row in rows:
                if row['submission_state'] in ('sending','uncertain'):
                    self.reconcile(client,row,jobs); self.persist(path,row)
                    uncertain |= row['submission_state'] in ('sending','uncertain')
                jid=str((row.get('job') or {}).get('id',''))
                if not jid:
                    continue
                job=jobs.get(jid)
                if not job:
                    row['note']='原上游任务列表未找到此编号；不切换接口、不重复提交。';self.persist(path,row);continue
                row['job']=brief(job); self.persist(path,row)
                if row['upstream']['protocol']=='wan-portal-v1':
                    row['note']=job.get('error_message') or ('万万工作台：'+(job.get('wait_label') or job['status'])+(f'；前面{job["queue_ahead"]}条' if job.get('queue_ahead') is not None else ''))
                    self.persist(path,row)
                if job.get('status')=='done' and job.get('has_video') and not row.get('download'):
                    item=row['source_item']; output=under(self.studio.root,item['episode_dir'])/'生成视频/看板重提'/(row['request_id']+'.mp4')
                    try:
                        result=client.download(jid,output)
                        row['download']={**result,'path':output.relative_to(self.studio.root).as_posix()}; row['note']='已下载；画面效果待验收。'
                    except Exception:
                        row['note']='已生成，下载失败，稍后继续下载，不重新生成。'
                    self.persist(path,row)
            if uncertain:
                continue
            pending=sorted([(p,r) for p,r in rows if r['submission_state'] in ('queued','waiting_key','capacity_wait')],key=lambda pr:(pr[1]['created_at'],pr[1]['order']))
            for path,row in pending:
                if self.stop.is_set():return
                if getattr(client, 'blocked_reason', ''):
                    row['submission_state']='capacity_wait';row['note']=client.blocked_reason;self.persist(path,row)
                    continue
                # Account-wide count includes jobs submitted by the agent, not only studio tasks.
                jobs=client.jobs()
                if sum(j.get('status') in ('pending','running') for j in jobs.values())>=row['upstream']['max_concurrency']:
                    row['submission_state']='capacity_wait';row['note']='优先排队：等待下一个空位，先于主队列未提交镜头。';self.persist(path,row);break
                if row.get('priority_retry_after',0)>time.time():continue
                item=row['source_item']
                if row['upstream']['protocol']=='wan-portal-v1':
                    try: ride=client.api('GET','/api/portal/ride')
                    except UpstreamError as error:
                        row['note']=str(error)+'；未创建新任务。';self.persist(path,row);break
                    if not ride.get('accepting'):
                        row['submission_state']='capacity_wait';row['note']='Wan当前班次未开放接单，队列保留，尚未扣费。';self.persist(path,row);break
                elif row['upstream']['protocol']=='scenora-v1':
                    model_id=row['upstream']['preset_map'].get(item['preset'],'wan3-pro')
                    try: svc=client.api('GET','/v1/service-status')
                    except UpstreamError as error:
                        row['note']=str(error)+'；未创建新任务。';self.persist(path,row);break
                    m_info=(svc.get('models') or {}).get(model_id) or {}
                    if not svc.get('enabled') or not m_info.get('enabled', True):
                        reason=m_info.get('reason') or svc.get('reason') or '当前模型暂未开放生成'
                        row['submission_state']='capacity_wait';row['note']=f'映流：{reason}；队列保留，尚未扣费。';self.persist(path,row);break
                try:
                    refs=[client.upload(under(self.studio.root,b['path']),b['sha256']) for b in item['bindings']]
                except Exception:
                    row['priority_retry_after']=time.time()+30;row['note']='上传未完成，30 秒后继续优先重试；尚未提交生成。';self.persist(path,row);break
                with submission_turn(self.studio.root, home_dir=self.studio.home):
                    # Another local worker may have submitted while we were uploading.
                    row=load_json(path)
                    if row['submission_state'] not in ('queued','waiting_key','capacity_wait'):continue
                    head=priority_head(self.studio.root, home_dir=self.studio.home)
                    if head and head['request_id']!=row['request_id']:continue
                    if row.get('priority_retry_after',0)>time.time():continue
                    # Refresh after uploads as they may take minutes.
                    jobs=client.jobs()
                    # A direct Doubao session has its own concurrency; an unrelated
                    # provider/account must not occupy this session's only slot.
                    other_active = 0 if row['upstream']['protocol'] == 'doubao-canvas-v1' else other_upstream_active(self.studio.root,row['upstream']['base_url'])
                    if sum(j.get('status') in ('pending','running') for j in jobs.values())+other_active>=row['upstream']['max_concurrency']:
                        row['submission_state']='capacity_wait';self.persist(path,row);break
                    if row['upstream']['protocol'] == 'doubao-canvas-v1':
                        try:
                            payload=client.payload(item, refs, row['request_id'], row.get('prepared_submission'))
                        except UpstreamError as error:
                            row['submission_state']='rejected';row['note']=str(error)+'；未发送视频生成请求。';self.persist(path,row);break
                        row['prepared_submission']=payload
                        # Freeze workspace/node and request ID before the generation POST.
                        self.persist(path,row)
                    row['baseline_job_ids']=list(jobs);row['submission_state']='sending';row['submitted_at']=stamp()
                    self.persist(path,row)
                    try:
                        if row['upstream']['protocol'] == 'doubao-canvas-v1':
                            pass  # Prepared packet already frozen before entering sending.
                        elif row['upstream']['protocol'] in ('sparkcine-v1','wan-portal-v1','scenora-v1','openai-video-v1'):
                            payload=client.payload(item,refs,row['request_id'])
                        else:
                            payload=client.payload(item,refs)
                        job=client.submit(payload)
                    except UpstreamError as error:
                        row['submission_state']='capacity_wait' if error.status==429 else ('uncertain' if error.status>=500 else 'rejected')
                        row['note']=str(error)+('；结果不明，不自动重发。' if error.status>=500 else '；原任务和视频保留。')
                    except Exception:
                        row['submission_state']='uncertain';row['note']='提交结果不明，不自动重发，请交由 agent 核对。'
                    else:
                        row['submission_state']='submitted';row['job']=brief(job);row.pop('priority_retry_after',None);row['note']='已优先提交至本次所选上游。'
                    self.persist(path,row)
                if row['submission_state'] in ('uncertain','capacity_wait','rejected'):
                    break
