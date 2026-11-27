from __future__ import annotations
import json, re, time
from typing import Any
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import get_db, SessionLocal
from .models import User, Experiment, Task, Assignment, Trace, ChatRequest, Event, ModelSnapshot, ExperimentConsent, MoralDilemmaSession, uid, utcnow
from .security import current_user, admin_user
from .telemetry import record_event
from .moral_dilemma import TASK_PROMPT, TASK_VERSION, TASK_SOURCE_SHA256, TASK_PROMPT_SHA256, STAGE_ORDER, FINAL_REFLECTION

router=APIRouter(tags=["moral-dilemma"])
CONSENT_VERSION="moral-dilemma-consent-v1"
TASK_CODE="MORAL-DILEMMA-01"

def stage_source(n:int)->str:
    m=re.search(rf"(?ms)^<STAGE {n} — .*?</STAGE {n} — [^>]+>",TASK_PROMPT)
    if not m: raise RuntimeError(f"Stage {n} missing from immutable task source")
    return m.group(0)

def model_config(arm):
    return (settings.llm_base_url,settings.llm_model,settings.llm_api_key,settings.llm_provider) if arm=="llm" else (settings.slm_base_url,settings.slm_model,settings.slm_api_key,settings.slm_provider)

async def participant_assignment(db,user):
    c=await db.scalar(select(ExperimentConsent).where(ExperimentConsent.participant_id==user.id).order_by(ExperimentConsent.accepted_at.desc()))
    if not c: raise HTTPException(403,"Experiment-specific consent required")
    a=await db.scalar(select(Assignment).where(Assignment.participant_id==user.id,Assignment.experiment_id==c.experiment_id))
    if not a: raise HTTPException(404,"No moral-dilemma assignment")
    s=await db.scalar(select(MoralDilemmaSession).where(MoralDilemmaSession.assignment_id==a.id))
    return c,a,s

@router.post("/api/admin/moral-dilemma/experiments",status_code=201)
async def create_experiment(body:dict[str,Any],db:AsyncSession=Depends(get_db),admin:User=Depends(admin_user)):
    name=str(body.get("name") or "Moral Dilemma Study").strip()
    approval=str(body.get("ethics_approval_ref") or "").strip()
    source_id=body.get("source_experiment_id")
    if len(name)<3 or not approval: raise HTTPException(422,"name and institutional ethics_approval_ref are required")
    snaps=(await db.scalars(select(ModelSnapshot).where(ModelSnapshot.experiment_id==source_id))).all() if source_id else []
    if {x.arm for x in snaps}!={"llm","slm"}: raise HTTPException(409,"source_experiment_id must have frozen LLM and SLM snapshots")
    exp=Experiment(name=name,description="Separate fixed-version moral-dilemma protocol.",status="ready",protocol_version=TASK_VERSION,seed=int(body.get("seed",20261125)),ethics_approved=True,ethics_approval_ref=approval,ethics_approved_at=utcnow(),ethics_approved_by=admin.id,created_by=admin.id)
    db.add(exp); await db.flush()
    for x in snaps:
        db.add(ModelSnapshot(experiment_id=exp.id,arm=x.arm,provider=x.provider,model_id=x.model_id,repository=x.repository,revision=x.revision,engine_version=x.engine_version,config=x.config,config_sha256=x.config_sha256,frozen_by=admin.id))
    task=Task(experiment_id=exp.id,task_code=TASK_CODE,title="Moral dilemma reasoning",prompt=TASK_PROMPT,instructions="Fixed application-controlled eight-stage task.",rubric={"evaluation":"No moral answer scoring or steering."},network_profile={"name":"baseline","latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0},model_arm="llm",task_order=1,active=True)
    db.add(task); await db.commit()
    return {"experiment_id":exp.id,"task_id":task.id,"task_version":TASK_VERSION,"task_source_sha256":TASK_SOURCE_SHA256,"task_prompt_sha256":TASK_PROMPT_SHA256}

@router.post("/api/admin/moral-dilemma/experiments/{experiment_id}/assign",status_code=201)
async def assign(experiment_id:str,body:dict[str,Any],db:AsyncSession=Depends(get_db),admin:User=Depends(admin_user)):
    exp=await db.get(Experiment,experiment_id)
    if not exp or exp.protocol_version!=TASK_VERSION or not exp.ethics_approved: raise HTTPException(404,"Approved moral-dilemma experiment not found")
    snaps=(await db.scalars(select(ModelSnapshot).where(ModelSnapshot.experiment_id==experiment_id))).all()
    if {x.arm for x in snaps}!={"llm","slm"}: raise HTTPException(409,"Both model arms must be frozen")
    task=await db.scalar(select(Task).where(Task.experiment_id==experiment_id,Task.task_code==TASK_CODE,Task.active==True))
    ids=list(dict.fromkeys(body.get("participant_ids") or [])); arms=body.get("model_arms") or ["llm","slm"]
    if not ids or any(x not in {"llm","slm"} for x in arms): raise HTTPException(422,"participant_ids and valid model_arms required")
    created=[]
    for i,pid in enumerate(ids):
        u=await db.get(User,pid)
        if not u or u.role!="participant" or not u.active: raise HTTPException(422,f"Invalid participant {pid}")
        old=await db.scalar(select(Assignment).where(Assignment.experiment_id==experiment_id,Assignment.participant_id==pid))
        if old: continue
        arm=arms[i%len(arms)]
        db.add(Assignment(experiment_id=experiment_id,task_id=task.id,participant_id=pid,sequence_no=1,condition_order=i+1,condition={"model_arm":arm,"network_profile":task.network_profile,"task_version":TASK_VERSION},status="assigned"))
        created.append({"participant_id":pid,"model_arm":arm})
    await db.commit()
    return {"created":created,"count":len(created)}

@router.get("/api/participant/moral-dilemma/consent")
async def consent_info(user:User=Depends(current_user)):
    return {"version":CONSENT_VERSION,"title":"Participation information","summary":"Participation involves an approximately 10-minute conversation about a sequence of moral dilemmas. Your prompts and AI responses, pseudonymous participant code, assigned model condition, and response timing/technical telemetry will be recorded. Participation is voluntary and you may stop at any time. Do not enter names, contact details, passwords, or other sensitive personal information. Use the institution-approved study information sheet for data access, retention, withdrawal, and contact arrangements."}

@router.post("/api/participant/moral-dilemma/consent")
async def accept_consent(body:dict[str,Any],db:AsyncSession=Depends(get_db),user:User=Depends(current_user)):
    if user.role!="participant" or not user.active: raise HTTPException(403,"Active participant required")
    if body.get("accepted") is not True or body.get("consent_version")!=CONSENT_VERSION: raise HTTPException(422,"Explicit current consent acceptance required")
    a=await db.scalar(select(Assignment).join(Experiment,Experiment.id==Assignment.experiment_id).where(Assignment.participant_id==user.id,Experiment.protocol_version==TASK_VERSION))
    if not a: raise HTTPException(404,"No moral-dilemma assignment")
    row=await db.scalar(select(ExperimentConsent).where(ExperimentConsent.experiment_id==a.experiment_id,ExperimentConsent.participant_id==user.id))
    if row: row.consent_version=CONSENT_VERSION; row.accepted_at=utcnow()
    else: db.add(ExperimentConsent(experiment_id=a.experiment_id,participant_id=user.id,consent_version=CONSENT_VERSION))
    await db.commit()
    return {"accepted":True,"consent_version":CONSENT_VERSION}

@router.get("/api/participant/moral-dilemma/session")
async def session_state(db:AsyncSession=Depends(get_db),user:User=Depends(current_user)):
    c,a,s=await participant_assignment(db,user)
    return {"assignment_id":a.id,"status":s.status if s else "not_started","active_stage":s.active_stage if s else None,"trace_id":s.trace_id if s else None,"task_version":TASK_VERSION}

@router.post("/api/participant/moral-dilemma/start")
async def start(db:AsyncSession=Depends(get_db),user:User=Depends(current_user)):
    if user.role!="participant" or not user.active: raise HTTPException(403,"Active participant required")
    c,a,s=await participant_assignment(db,user)
    if s: raise HTTPException(409,"Session already started")
    task=await db.get(Task,a.task_id)
    if not task or task.prompt!=TASK_PROMPT: raise HTTPException(409,"Immutable task definition mismatch")
    arm=(a.condition or {}).get("model_arm","llm")
    trace=Trace(experiment_id=a.experiment_id,task_id=task.id,assignment_id=a.id,participant_id=user.id,model_arm=arm,client_metadata={"task_version":TASK_VERSION,"task_source_sha256":TASK_SOURCE_SHA256})
    db.add(trace); await db.flush()
    s=MoralDilemmaSession(experiment_id=a.experiment_id,assignment_id=a.id,trace_id=trace.id,participant_id=user.id,task_version=TASK_VERSION,task_source_sha256=TASK_SOURCE_SHA256,active_stage=0,status="active",transcript=[])
    db.add(s); a.status="in_progress"; a.started_at=utcnow()
    await record_event(db,trace.id,"moral_dilemma_started",{"task_version":TASK_VERSION,"task_source_sha256":TASK_SOURCE_SHA256,"stage":0,"model_arm":arm},participant_id=user.id)
    await db.commit()
    return {"started":True,"session_id":s.id,"trace_id":trace.id,"active_stage":0}

@router.post("/api/participant/moral-dilemma/turn")
async def turn(body:dict[str,Any],db:AsyncSession=Depends(get_db),user:User=Depends(current_user)):
    if user.role!="participant" or not user.active: raise HTTPException(403,"Active participant required")
    c,a,s=await participant_assignment(db,user)
    if not s or s.status!="active": raise HTTPException(409,"No active session")
    action=body.get("action"); text=str(body.get("text") or "").strip()
    if action not in {"clarify","continue","final_reflection"} or not text or len(text)>settings.max_prompt_chars: raise HTTPException(422,"Valid action and non-empty text required")
    if action=="final_reflection" and not s.final_reflection_requested: raise HTTPException(409,"Final reflection is not open")
    if action!="final_reflection" and s.final_reflection_requested: raise HTTPException(409,"Final reflection is active")
    stage=s.active_stage
    if action=="continue":
        s.transcript.append({"role":"user","content":text,"stage":stage,"action":"submitted_answer"})
        if stage==7:
            s.final_reflection_requested=True
            acknowledgement="Thank you for explaining your reasoning."
            s.transcript.append({"role":"assistant","content":acknowledgement,"stage":7,"action":"brief_acknowledgement"})
            await record_event(db,s.trace_id,"moral_dilemma_stage_7_answered",{"stage":7,"brief_acknowledgement":True},participant_id=user.id)
            await db.commit()
            return JSONResponse({"final_reflection_available":True,"acknowledgement":acknowledgement,"final_reflection_prompt":FINAL_REFLECTION,"active_stage":7})
        s.active_stage=stage+1
    elif action=="clarify":
        s.transcript.append({"role":"user","content":text,"stage":stage,"action":"clarification"})
    else:
        s.transcript.append({"role":"user","content":text,"stage":"final_reflection","action":"final_reflection"})
        s.status="completed"; s.completed_at=utcnow(); a.status="completed"; a.completed_at=utcnow()
        await record_event(db,s.trace_id,"moral_dilemma_completed",{"task_version":TASK_VERSION},participant_id=user.id)
        await db.commit()
        return {"completed":True}
    current=s.active_stage
    arm=(a.condition or {}).get("model_arm","llm")
    base,model,key,provider=model_config(arm)
    messages=[{"role":"system","content":TASK_PROMPT+"\n\nAPPLICATION-CONTROLLED STAGE: "+str(current)+".\nCURRENT STAGE TEXT (verbatim):\n"+stage_source(current)+"\nOnly handle this stage. Respond to the participant's previous reasoning, then present this stage's fixed question. Do not introduce future stages or ask additional substantive questions. Never score or steer moral judgments. Stage number is authoritative."}]
    messages.extend({"role":x["role"],"content":x["content"]} for x in s.transcript[-30:] if x.get("role") in {"user","assistant"})
    request_id=uid("req")
    row=ChatRequest(id=request_id,trace_id=s.trace_id,participant_id=user.id,prompt=text,provider_model=model,status="running")
    db.add(row)
    await record_event(db,s.trace_id,"moral_dilemma_turn_started",{"stage":current,"action":action,"arm":arm,"provider":provider,"model":model},request_id,user.id)
    await db.commit()
    async def stream():
        started=time.perf_counter(); first=None; parts=[]; tokens=0
        try:
            yield f"event: metadata\ndata: {json.dumps({'request_id':request_id,'stage':current,'provider':provider,'model':model})}\n\n"
            headers={"Content-Type":"application/json"}
            if key: headers["Authorization"]="Bearer "+key
            payload={"model":model,"messages":messages,"stream":True,"stream_options":{"include_usage":True},"max_tokens":settings.max_output_tokens,"temperature":settings.temperature,"top_p":settings.top_p,"seed":settings.inference_seed}
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15,read=300,write=30,pool=15),verify=settings.inference_ca_bundle or True) as client:
                async with client.stream("POST",base.rstrip("/")+"/chat/completions",json=payload,headers=headers) as resp:
                    if resp.status_code>=400: raise RuntimeError("INFERENCE_HTTP_"+str(resp.status_code))
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"): continue
                        raw=line[5:].strip()
                        if raw=="[DONE]": break
                        try: packet=json.loads(raw)
                        except Exception: continue
                        if packet.get("usage"): tokens=int(packet["usage"].get("completion_tokens") or tokens)
                        choices=packet.get("choices") or []
                        if choices:
                            part=(choices[0].get("delta") or {}).get("content")
                            if part:
                                if first is None: first=time.perf_counter()
                                parts.append(part)
                                yield f"event: delta\ndata: {json.dumps({'text':part,'stage':current})}\n\n"
            answer="".join(parts); elapsed=(time.perf_counter()-started)*1000
            async with SessionLocal() as d:
                rr=await d.get(ChatRequest,request_id); rr.response_text=answer; rr.status="completed"; rr.ttft_ms=(first-started)*1000 if first else None; rr.e2e_latency_ms=elapsed; rr.output_tokens=tokens; rr.response_chars=len(answer); rr.response_bytes=len(answer.encode()); rr.completed_at=utcnow()
                ss=await d.get(MoralDilemmaSession,s.id); ss.transcript.append({"role":"assistant","content":answer,"stage":current})
                await record_event(d,ss.trace_id,"moral_dilemma_turn_completed",{"stage":current,"action":action,"ttft_ms":rr.ttft_ms,"e2e_latency_ms":elapsed,"output_tokens":tokens,"response_bytes":rr.response_bytes},request_id,user.id)
                await d.commit()
            yield f"event: completed\ndata: {json.dumps({'stage':current,'status':'completed'})}\n\n"
        except Exception as exc:
            async with SessionLocal() as d:
                rr=await d.get(ChatRequest,request_id)
                if rr: rr.status="failed"; rr.error_code=type(exc).__name__; rr.completed_at=utcnow()
                await record_event(d,s.trace_id,"moral_dilemma_turn_failed",{"stage":current,"error_type":type(exc).__name__},request_id,user.id)
                await d.commit()
            yield f"event: error\ndata: {json.dumps({'error':'Response generation failed'})}\n\n"
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})

@router.get("/api/admin/moral-dilemma/export.json")
async def export_data(db:AsyncSession=Depends(get_db),admin:User=Depends(admin_user)):
    sessions=(await db.scalars(select(MoralDilemmaSession).order_by(MoralDilemmaSession.started_at))).all()
    out=[]
    for s in sessions:
        a=await db.get(Assignment,s.assignment_id); u=await db.get(User,s.participant_id)
        reqs=(await db.scalars(select(ChatRequest).where(ChatRequest.trace_id==s.trace_id).order_by(ChatRequest.started_at))).all()
        evs=(await db.scalars(select(Event).where(Event.trace_id==s.trace_id).order_by(Event.occurred_at))).all()
        out.append({"session_id":s.id,"experiment_id":s.experiment_id,"trace_id":s.trace_id,"participant_code":u.participant_code if u else None,"model_arm":(a.condition or {}).get("model_arm") if a else None,"task_version":s.task_version,"task_source_sha256":s.task_source_sha256,"active_stage":s.active_stage,"status":s.status,"transcript":s.transcript,"requests":[{"id":r.id,"prompt":r.prompt,"response":r.response_text,"status":r.status,"ttft_ms":r.ttft_ms,"e2e_latency_ms":r.e2e_latency_ms,"output_tokens":r.output_tokens,"response_bytes":r.response_bytes} for r in reqs],"events":[{"type":e.event_type,"at":e.occurred_at.isoformat(),"payload":e.payload} for e in evs]})
    return JSONResponse(out,headers={"Content-Disposition":"attachment; filename=moral-dilemma-export.json"})

@router.get("/moral-dilemma",response_class=HTMLResponse)
async def participant_page():
    return HTMLResponse("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Conversation</title><style>body{font:16px system-ui;background:#f3f5f7;color:#18212b;max-width:850px;margin:30px auto;padding:16px}section{background:white;border:1px solid #dce2e8;border-radius:12px;padding:18px;margin:12px 0}textarea{width:100%;min-height:110px;padding:10px;font:inherit}button{padding:11px 16px;margin:6px;border:0;border-radius:7px;background:#20364b;color:white}#chat{white-space:pre-wrap;line-height:1.5}</style></head><body><h1>Conversation</h1><section id='consent'><p id='info'>Loading participation information…</p><label><input type='checkbox' id='agree'> I agree to participate.</label><p><button id='start'>Continue</button></p></section><section id='room' hidden><div id='chat'></div><textarea id='text' placeholder='Write your response or clarification'></textarea><button id='clarify'>Ask clarification</button><button id='continue'>Submit response / Continue</button><p id='status'></p></section><script>const $=x=>document.getElementById(x);let stage=0;async function req(url,body){let r=await fetch(url,{method:body?'POST':'GET',credentials:'include',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent((document.cookie.split('; ').find(x=>x.startsWith('qoe_csrf='))||'').split('=').slice(1).join('='))},body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error(await r.text());return r}async function stream(action,text){let r=await req('/api/participant/moral-dilemma/turn',{action,text}),reader=r.body.getReader(),dec=new TextDecoder(),buf='';while(1){let x=await reader.read();if(x.done)break;buf+=dec.decode(x.value,{stream:true});let b=buf.split('\\n\\n');buf=b.pop();for(let q of b){let ev=(q.match(/^event: (.+)$/m)||[])[1],d=(q.match(/^data: (.+)$/m)||[])[1];if(!d)continue;let v=JSON.parse(d);if(ev==='delta')$('chat').textContent+=v.text;if(ev==='completed')$('status').textContent='Response received';if(ev==='error')throw Error(v.error)}}}async function init(){let d=await (await req('/api/participant/moral-dilemma/consent')).json();$('info').textContent=d.summary}$('start').onclick=async()=>{try{if(!$('agree').checked)throw Error('Consent required');await req('/api/participant/moral-dilemma/consent',{accepted:true,consent_version:'moral-dilemma-consent-v1'});await req('/api/participant/moral-dilemma/start',{});$('consent').hidden=true;$('room').hidden=false;await stream('clarify','Please begin Stage 0 with the fixed initial situation and question.')}catch(e){alert(e.message)}};$('clarify').onclick=async()=>{let t=$('text').value.trim();if(!t)return;$('chat').textContent+='\\nYou: '+t+'\\n';$('text').value='';try{await stream('clarify',t)}catch(e){alert(e.message)}};$('continue').onclick=async()=>{let t=$('text').value.trim();if(!t)return;$('chat').textContent+='\\nYou: '+t+'\\n';$('text').value='';try{let r=await req('/api/participant/moral-dilemma/turn',{action:'continue',text:t});if((r.headers.get('content-type')||'').includes('application/json')){let d=await r.json();if(d.final_reflection_available){$('chat').textContent+='\\n'+d.acknowledgement+'\\n\\n'+d.final_reflection_prompt+'\\n';$('clarify').hidden=true;$('continue').textContent='Submit final reflection';$('continue').onclick=async()=>{let a=$('text').value.trim();if(a){await req('/api/participant/moral-dilemma/turn',{action:'final_reflection',text:a});$('status').textContent='Completed';$('continue').disabled=true}}}return}const reader=r.body.getReader(),dec=new TextDecoder();let buf='';while(1){let x=await reader.read();if(x.done)break;buf+=dec.decode(x.value,{stream:true});let blocks=buf.split('\\n\\n');buf=blocks.pop();for(let b of blocks){let ev=(b.match(/^event: (.+)$/m)||[])[1],data=(b.match(/^data: (.+)$/m)||[])[1];if(!data)continue;let d=JSON.parse(data);if(ev==='delta')$('chat').textContent+=d.text;if(ev==='completed')$('status').textContent='Stage '+(d.stage+1)+' response received';if(ev==='error')throw Error(d.error)}}}catch(e){alert(e.message)}};init().catch(e=>$('info').textContent=e.message);</script></body></html>")
