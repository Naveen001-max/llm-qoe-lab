import asyncio, json, time, uuid, os, hashlib, re
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import httpx, secrets, hmac
from redis.asyncio import Redis
from redis.exceptions import RedisError
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from .config import settings
from .db import Base, engine, get_db, SessionLocal
from .models import User, Experiment, Task, Assignment, Trace, ChatRequest, Questionnaire, RubricScore, Event, ModelSnapshot, uid, utcnow
from .security import hash_password, verify_password, create_access_token, current_user, admin_user
from .schemas import LoginIn, ParticipantCreate, ExperimentCreate, TaskSeedIn, RandomizeIn, ChatIn, EventIn, QuestionnaireIn, RubricScoreIn, ModelFreezeIn, PrepareIn, ConsentIn, EthicsApprovalIn
from .telemetry import record_event
from .protocol import task_records, NASA_TLX, P852_QOE, NETWORK_PROFILES, CONSENT_SUMMARY

REQUESTS = Counter("llm_qoe_requests_total","LLM QoE API requests",["route","status"])
STREAM_E2E = Histogram("llm_qoe_stream_e2e_seconds","End-to-end streaming latency")
TTFT = Histogram("llm_qoe_ttft_seconds","Time to first visible output")
QUEUE = Histogram("llm_qoe_queue_seconds","Application admission queue time")
ACTIVE = asyncio.Semaphore(int(os.getenv("API_MAX_CONCURRENT_STREAMS","32")))
# NetEm is a shared physical gateway profile. Serialize full requests so one
# participant cannot change another participant's network condition.
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)

async def apply_gateway_profile(profile: dict):
    if not settings.gateway_control_url:
        if settings.require_gateway:
            raise RuntimeError("GATEWAY_NOT_CONFIGURED")
        return {"applied":False,"reason":"gateway control URL not configured"}
    if not settings.gateway_token:
        raise RuntimeError("GATEWAY_TOKEN_NOT_CONFIGURED")
    config={k:profile.get(k,0) for k in ("latency_ms","jitter_ms","loss_pct","bandwidth_mbps")}
    async with httpx.AsyncClient(
        timeout=15,
        verify=settings.gateway_ca_bundle or True,
    ) as client:
        response=await client.post(
            settings.gateway_control_url.rstrip("/")+"/profile",
            json=config,
            headers={"Authorization":f"Bearer {settings.gateway_token}"},
        )
        response.raise_for_status()
        return response.json()

async def get_gateway_status():
    if not settings.gateway_control_url or not settings.gateway_token:
        return {"available":False}
    async with httpx.AsyncClient(
        timeout=15,
        verify=settings.gateway_ca_bundle or True,
    ) as client:
        response=await client.get(
            settings.gateway_control_url.rstrip("/")+"/status",
            headers={"Authorization":f"Bearer {settings.gateway_token}"},
        )
        response.raise_for_status()
        return response.json()

def calculate_qdisc_deltas(start_snapshot: dict | None, end_snapshot: dict | None):
    """Return per-qdisc tc counter deltas; preserve WAN and IFB directions separately."""
    if not start_snapshot or not end_snapshot:
        return {"available": False, "reason": "missing_start_or_end_qdisc_snapshot"}
    fields = ("bytes", "packets", "dropped", "overlimits", "requeues")
    result = {"available": True, "counter_source": "tc -s qdisc show",
              "wan_interface": end_snapshot.get("wan_interface"),
              "ifb_interface": end_snapshot.get("ifb_interface"),
              "wan_qdisc_deltas": [], "ifb_qdisc_deltas": [],
              "measurement_note": (
                  "Counters are per qdisc and are not summed across parent/child qdiscs. "
                  "The window begins after profile application and ends before baseline reset. "
                  "It includes a small amount of gateway-control traffic and is not a pure application-packet count."
              )}
    for source_key, target_key in (("wan_qdiscs", "wan_qdisc_deltas"), ("ifb_qdiscs", "ifb_qdisc_deltas")):
        before = {(x.get("device"), x.get("kind"), x.get("handle"), x.get("placement")): x
                  for x in start_snapshot.get(source_key, [])}
        after = {(x.get("device"), x.get("kind"), x.get("handle"), x.get("placement")): x
                 for x in end_snapshot.get(source_key, [])}
        for key in sorted(set(before) | set(after), key=lambda x: tuple(str(v) for v in x)):
            old, new = before.get(key), after.get(key)
            row = {"device": key[0], "kind": key[1], "handle": key[2], "placement": key[3],
                   "counter_reset_or_qdisc_changed": old is None or new is None}
            for field in fields:
                if old is None or new is None:
                    row[field] = None
                else:
                    delta = int(new.get(field, 0)) - int(old.get(field, 0))
                    row[field] = delta if delta >= 0 else None
                    if delta < 0:
                        row["counter_reset_or_qdisc_changed"] = True
            result[target_key].append(row)
    return result

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema lifecycle is owned by Alembic migrations in the container entrypoint.
    # Bootstrap is only performed when explicitly configured; never print password.
    if settings.admin_bootstrap_password:
        async with SessionLocal() as db:
            existing = await db.scalar(select(User).where(User.username == settings.admin_bootstrap_username))
            if not existing:
                db.add(User(username=settings.admin_bootstrap_username,
                            password_hash=hash_password(settings.admin_bootstrap_password),
                            role="admin", active=True))
                await db.commit()
    yield
    await redis_client.aclose()
    await engine.dispose()

app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                   allow_credentials=True, allow_methods=["GET","POST","PATCH","OPTIONS"],
                   allow_headers=["Authorization","Content-Type","X-Trace-ID","X-Client-Event-ID","X-CSRF-Token"])

from .moral_dilemma_api import router as moral_dilemma_router
app.include_router(moral_dilemma_router)

@app.middleware("http")
async def request_context(request: Request, call_next):
    trace = request.headers.get("X-Trace-ID") or f"trc_{uuid.uuid4().hex}"
    request.state.trace_id = trace
    started=time.perf_counter()
    try:
        response=await call_next(request)
        response.headers["X-Trace-ID"]=trace
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="same-origin"
        response.headers["Cache-Control"]="no-store" if request.url.path.startswith("/api") else "no-cache"
        route=request.scope.get("route")
        route_name=getattr(route,"path",request.url.path)
        REQUESTS.labels(route_name,str(response.status_code)).inc()
        return response
    except Exception:
        route=request.scope.get("route")
        route_name=getattr(route,"path",request.url.path)
        REQUESTS.labels(route_name,"500").inc()
        raise

@app.middleware("http")
async def rate_limit_guard(request: Request, call_next):
    if request.method=="POST" and request.url.path in {"/api/auth/login","/api/chat/stream"}:
        ip=request.client.host if request.client else "unknown"
        limit=10 if request.url.path=="/api/auth/login" else settings.rate_limit_per_minute
        key=f"rate:{request.url.path}:{ip}"
        try:
            count=await redis_client.incr(key)
            if count==1: await redis_client.expire(key,60)
            if count>limit: return JSONResponse({"detail":"Rate limit exceeded; retry later"},status_code=429)
        except RedisError:
            if settings.app_env=="production":
                return JSONResponse({"detail":"Rate limiter unavailable"},status_code=503)
    return await call_next(request)

@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.method in {"POST","PUT","PATCH","DELETE"} and request.url.path not in {"/api/auth/login"}:
        cookie=request.cookies.get("qoe_csrf")
        header=request.headers.get("X-CSRF-Token")
        if request.cookies.get("qoe_access") and (not cookie or not header or not hmac.compare_digest(cookie,header)):
            return JSONResponse({"detail":"CSRF token missing or invalid"},status_code=403)
    return await call_next(request)

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("qoe_access",path="/")
    response.delete_cookie("qoe_csrf",path="/")
    return {"logged_out":True}

@app.get("/health/live")
async def live():
    return {"status":"alive","service":"llm-qoe-api"}

@app.get("/health/ready")
async def ready(db: AsyncSession=Depends(get_db)):
    try:
        await db.execute(select(1))
        await redis_client.ping()
        return {"status":"ready","database":"ok","redis":"ok"}
    except Exception:
        raise HTTPException(503,"Database unavailable")

@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)

@app.post("/api/auth/login")
async def login(body: LoginIn, response: Response, db: AsyncSession=Depends(get_db)):
    user=await db.scalar(select(User).where(User.username==body.username))
    if not user or not user.active or not verify_password(body.password,user.password_hash):
        raise HTTPException(401,"Invalid username or password")
    token=create_access_token(user)
    csrf=secrets.token_urlsafe(32)
    response.set_cookie("qoe_access",token,httponly=True,secure=settings.cookie_secure,
                        samesite="strict",max_age=settings.access_token_minutes*60,path="/")
    response.set_cookie("qoe_csrf",csrf,httponly=False,secure=settings.cookie_secure,
                        samesite="strict",max_age=settings.access_token_minutes*60,path="/")
    return {"authenticated":True,"expires_in":settings.access_token_minutes*60,
            "user":{"id":user.id,"username":user.username,"role":user.role,"participant_code":user.participant_code}}

@app.get("/api/auth/me")
async def me(user: User=Depends(current_user)):
    return {"id":user.id,"username":user.username,"role":user.role,"participant_code":user.participant_code,
            "consent_at":user.consent_at.isoformat() if user.consent_at else None,
            "consent_version":user.consent_version}

@app.post("/api/admin/participants", status_code=201)
async def create_participant(body: ParticipantCreate, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    if await db.scalar(select(User).where(User.username==body.username)):
        raise HTTPException(409,"Username already exists")
    user=User(username=body.username,password_hash=hash_password(body.password),
              role="participant",participant_code=f"P-{uuid.uuid4().hex[:10].upper()}")
    db.add(user); await db.commit(); await db.refresh(user)
    return {"id":user.id,"username":user.username,"participant_code":user.participant_code}

@app.get("/api/admin/participants")
async def participants(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    rows=(await db.scalars(select(User).where(User.role=="participant").order_by(User.created_at.desc()))).all()
    return [{"id":u.id,"username":u.username,"participant_code":u.participant_code,"active":u.active,
        "consent_version":u.consent_version,"consent_at":u.consent_at.isoformat() if u.consent_at else None} for u in rows]

@app.post("/api/admin/experiments",status_code=201)
async def create_experiment(body: ExperimentCreate, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    if body.ethics_approved and not body.ethics_approval_ref.strip():
        raise HTTPException(422,"An ethics approval reference is required when marking the study approved")
    exp=Experiment(name=body.name,description=body.description,seed=body.seed,
        protocol_version=settings.consent_version,ethics_approved=body.ethics_approved,
        ethics_approval_ref=body.ethics_approval_ref.strip() or None,
        ethics_approved_at=utcnow() if body.ethics_approved else None,
        ethics_approved_by=admin.id if body.ethics_approved else None,created_by=admin.id)
    db.add(exp); await db.commit(); await db.refresh(exp)
    return {"id":exp.id,"name":exp.name,"status":exp.status,"seed":exp.seed}

@app.get("/api/admin/experiments")
async def experiments(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    rows=(await db.scalars(select(Experiment).order_by(Experiment.created_at.desc()))).all()
    return [{"id":e.id,"name":e.name,"status":e.status,"protocol_version":e.protocol_version,
        "ethics_approved":e.ethics_approved,"ethics_approval_ref":e.ethics_approval_ref} for e in rows]

@app.post("/api/admin/experiments/{experiment_id}/ethics-approval")
async def record_ethics_approval(experiment_id: str, body: EthicsApprovalIn,
    db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    exp=await db.get(Experiment,experiment_id)
    if not exp: raise HTTPException(404,"Experiment not found")
    if not body.approved or not body.approval_ref.strip():
        raise HTTPException(422,"A formal approval reference and approved=true are required")
    exp.ethics_approved=True; exp.ethics_approval_ref=body.approval_ref.strip()
    exp.ethics_approved_at=utcnow(); exp.ethics_approved_by=admin.id
    await db.commit()
    return {"ethics_approved":True,"approval_ref":exp.ethics_approval_ref,
            "approved_at":exp.ethics_approved_at.isoformat()}

@app.post("/api/admin/experiments/{experiment_id}/seed-tasks")
async def seed_tasks(experiment_id: str, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    exp=await db.get(Experiment,experiment_id)
    if not exp: raise HTTPException(404,"Experiment not found")
    existing=await db.scalar(select(func.count(Task.id)).where(Task.experiment_id==experiment_id))
    if existing: raise HTTPException(409,"Tasks already exist; refusing to overwrite protocol")
    created=[]
    for item in task_records():
        row=Task(experiment_id=experiment_id,**item)
        db.add(row); created.append(row)
    await db.commit()
    return {"created":len(created),"task_codes":[x["task_code"] for x in task_records()]}

@app.get("/api/admin/experiments/{experiment_id}/tasks")
async def list_tasks(experiment_id: str, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    rows=(await db.scalars(select(Task).where(Task.experiment_id==experiment_id).order_by(Task.task_order))).all()
    return [{"id":t.id,"task_code":t.task_code,"title":t.title,"instructions":t.instructions,"rubric":t.rubric} for t in rows]

@app.post("/api/admin/experiments/{experiment_id}/model-freeze")
async def freeze_models(experiment_id: str, body: ModelFreezeIn, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    """Freeze server-owned model identity; never trust provider/model settings from the browser."""
    exp = await db.get(Experiment, experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    if {item.get("arm") for item in body.models} != {"llm", "slm"}:
        raise HTTPException(422, "Submit exactly one LLM arm and one SLM arm")

    saved = []
    for item in body.models:
        arm = item["arm"]
        provider = settings.llm_provider if arm == "llm" else settings.slm_provider
        model_id = settings.llm_model if arm == "llm" else settings.slm_model
        repository = settings.llm_model_repository if arm == "llm" else settings.slm_model_repository
        revision = settings.llm_model_revision if arm == "llm" else settings.slm_model_revision
        base_url = settings.llm_base_url if arm == "llm" else settings.slm_base_url
        api_key = settings.llm_api_key if arm == "llm" else settings.slm_api_key
        max_model_len = settings.llm_max_model_len if arm == "llm" else settings.slm_max_model_len
        max_num_seqs = settings.llm_max_num_seqs if arm == "llm" else settings.slm_max_num_seqs

        if not model_id or not base_url:
            raise HTTPException(409, f"{arm.upper()} provider, model ID and base URL must be configured server-side")

        config = {
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "seed": settings.inference_seed,
            "max_output_tokens": settings.max_output_tokens,
            "max_model_len": max_model_len,
            "max_num_seqs": max_num_seqs,
            "provider": provider,
            "provenance_status": "verified_runtime" if provider == "vllm" else "configured_provider_identity",
            "weights_immutable": bool(provider == "vllm" and repository and revision),
        }
        engine_version = "provider-managed"
        stored_repository = repository or f"{provider}-managed"
        stored_revision = revision or "provider-managed"

        if provider == "vllm":
            if not repository or not revision or len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision.lower()):
                raise HTTPException(409, f"{arm.upper()} vLLM requires configured repository and immutable 40-character commit SHA")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", settings.vllm_image_digest):
                raise HTTPException(409, "Set the verified vLLM image digest in VLLM_IMAGE_DIGEST before freezing")
            config.update({
                "vllm_image_digest": settings.vllm_image_digest,
                "prefix_caching": False,
                "extensible_kv_cache": False,
                "block_size": 16,
                "dtype": "auto",
                "gpu_memory_utilization": 0.90,
            })
            engine_version = f"vLLM {settings.vllm_version}"
            config["provenance_status"] = "verified_runtime"
            config["weights_immutable"] = True
            try:
                async with httpx.AsyncClient(timeout=10, verify=settings.inference_ca_bundle or True) as client:
                    auth_headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                    model_response = await client.get(base_url.rstrip("/") + "/models", headers=auth_headers)
                    model_response.raise_for_status()
                    served = [x.get("id") for x in model_response.json().get("data", [])]
                    version_response = await client.get(base_url.rsplit("/v1", 1)[0] + "/version", headers=auth_headers)
                    version_response.raise_for_status()
                    actual_version = str(version_response.json().get("version", ""))
                if model_id not in served:
                    raise HTTPException(409, f"Configured {arm.upper()} model alias is not served by inference endpoint")
                if settings.vllm_version not in actual_version:
                    raise HTTPException(409, f"Running inference engine version {actual_version} does not match pinned {settings.vllm_version}")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(503, f"{arm.upper()} inference endpoint is not healthy: {type(exc).__name__}")
        elif provider == "llama_cpp":
            # Model checksum/runtime version must be recorded separately when available.
            config["provenance_status"] = "configured_runtime_unverified"
            config["weights_immutable"] = False
        elif provider in {"groq", "gemini", "openai_compatible"}:
            # API providers control model weights and revisions; do not invent a commit SHA.
            stored_repository = f"{provider}-managed"
            stored_revision = "provider-managed"
            config["provenance_status"] = "provider_managed_weights"
            config["weights_immutable"] = False
        else:
            raise HTTPException(422, f"Unsupported provider for {arm.upper()}: {provider}")

        config["model_id"] = model_id
        identity = {"provider": provider, "model_id": model_id, "repository": stored_repository,
                    "revision": stored_revision, "engine_version": engine_version, "config": config}
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        existing = await db.scalar(select(ModelSnapshot).where(
            ModelSnapshot.experiment_id == experiment_id, ModelSnapshot.arm == arm))
        if existing:
            if (existing.provider != provider or existing.model_id != model_id or
                existing.revision != stored_revision or existing.config_sha256 != digest):
                raise HTTPException(409, f"{arm.upper()} model is already frozen; create a new experiment to change it")
            saved.append(existing)
        else:
            row = ModelSnapshot(
                experiment_id=experiment_id, arm=arm, provider=provider, model_id=model_id,
                repository=stored_repository, revision=stored_revision, engine_version=engine_version,
                config=config, config_sha256=digest, frozen_by=admin.id)
            db.add(row)
            saved.append(row)
    await db.commit()
    return {"frozen": [{
        "arm": row.arm, "provider": row.provider, "model_id": row.model_id,
        "repository": row.repository, "revision": row.revision,
        "engine_version": row.engine_version, "config_sha256": row.config_sha256,
        "provenance_status": row.config.get("provenance_status")
    } for row in saved]}

@app.post("/api/admin/experiments/{experiment_id}/randomize")
async def randomize(experiment_id: str, body: RandomizeIn, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    import random
    exp=await db.get(Experiment,experiment_id)
    if not exp: raise HTTPException(404,"Experiment not found")
    tasks=(await db.scalars(select(Task).where(Task.experiment_id==experiment_id,Task.active==True).order_by(Task.task_order))).all()
    frozen=(await db.scalars(select(ModelSnapshot).where(ModelSnapshot.experiment_id==experiment_id))).all()
    if not exp.ethics_approved or not exp.ethics_approval_ref:
        raise HTTPException(409,"Record formal institutional ethics approval before participant randomisation")
    if {m.arm for m in frozen}!={"llm","slm"}: raise HTTPException(409,"Freeze both LLM and SLM model revisions/configurations before randomisation")
    if len(tasks)!=12: raise HTTPException(409,"The protocol requires exactly 12 active controlled tasks before randomisation")
    if set(body.model_arms)!={"llm","slm"}: raise HTTPException(422,"The controlled study requires both LLM and SLM arms")
    if not body.network_profiles: raise HTTPException(422,"At least one network profile is required")
    gateway_configured=bool(settings.gateway_control_url and settings.gateway_token)
    for profile in body.network_profiles:
        bounds={"latency_ms":(0,2000),"jitter_ms":(0,500),"loss_pct":(0,30),"bandwidth_mbps":(0,1000),"word_delay_ms":(0,10000)}
        if not profile.get("name"): raise HTTPException(422,"Every network profile requires a name")
        for key,(lo,hi) in bounds.items():
            try: value=float(profile.get(key,0))
            except (TypeError,ValueError): raise HTTPException(422,f"Invalid {key} in network profile")
            if not lo<=value<=hi: raise HTTPException(422,f"{key} must be between {lo} and {hi}")
        if not gateway_configured and any(float(profile.get(k,0)) != 0 for k in ("latency_ms","jitter_ms","loss_pct","bandwidth_mbps")):
            raise HTTPException(409,"Network impairment is disabled because no gateway controller is configured. Use baseline-only profiles until the participant network path and gateway are verified.")
    rng=random.Random(exp.seed)
    made=0
    for pid in body.participant_ids:
        participant=await db.get(User,pid)
        if not participant or not participant.active or participant.role!="participant": raise HTTPException(404,f"Participant {pid} not found or inactive")
        if not participant.consent_at or participant.consent_version!=exp.protocol_version:
            raise HTTPException(409,f"Participant {pid} has not consented to protocol version {exp.protocol_version}")
        order=list(tasks); rng.shuffle(order)
        conditions=[{"model_arm":arm,"network_profile":profile}
                    for arm in body.model_arms for profile in body.network_profiles]
        rng.shuffle(conditions)
        for seq,task in enumerate(order,1):
            condition=conditions[(seq-1)%len(conditions)]
            arm=condition["model_arm"]
            profile=condition["network_profile"]
            exists=await db.scalar(select(Assignment.id).where(Assignment.task_id==task.id,Assignment.participant_id==pid))
            if exists: continue
            db.add(Assignment(experiment_id=experiment_id,task_id=task.id,participant_id=pid,
                              sequence_no=seq,condition_order=seq,
                              condition=condition))
            made+=1
    await db.commit()
    return {"created_assignments":made,"seed":exp.seed,"randomisation":"seeded participant-specific task order; model/network conditions counterbalanced by sequence"}
@app.get("/api/participant/assignments")
async def my_assignments(db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role!="participant" or not user.consent_at or user.consent_version!=settings.consent_version:
        raise HTTPException(403,"Current study consent is required")
    rows=(await db.execute(select(Assignment,Task).join(Task,Task.id==Assignment.task_id)
                           .where(Assignment.participant_id==user.id).order_by(Assignment.sequence_no))).all()
    return [{"assignment_id":a.id,"sequence":a.sequence_no,"status":a.status,"task_id":t.id,
             "task_code":t.task_code,"title":t.title,"prompt":t.prompt,"instructions":t.instructions,
             "model_arm":(a.condition or {}).get("model_arm","llm"),
             "network_profile":(a.condition or {}).get("network_profile",{})} for a,t in rows]

@app.post("/api/participant/traces",status_code=201)
async def create_trace(body: dict, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role!="participant" or not user.consent_at or user.consent_version!=settings.consent_version:
        raise HTTPException(403,"Current study consent is required")
    aid=body.get("assignment_id")
    assignment=await db.get(Assignment,aid)
    if not assignment or assignment.participant_id!=user.id: raise HTTPException(404,"Assignment not found")
    task=await db.get(Task,assignment.task_id)
    trace=Trace(experiment_id=assignment.experiment_id,task_id=task.id,assignment_id=aid,
                participant_id=user.id,model_arm=(assignment.condition or {}).get("model_arm","llm"),
                client_metadata=body.get("client_metadata",{}))
    db.add(trace); await db.flush()
    await record_event(db,trace.id,"trace_started",{"assignment_id":aid},participant_id=user.id)
    assignment.status="in_progress"
    if not assignment.started_at: assignment.started_at=utcnow()
    await db.commit()
    return {"trace_id":trace.id,"experiment_id":trace.experiment_id,"task_id":trace.task_id}

@app.post("/api/participant/events",status_code=202)
async def client_event(body: EventIn, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    trace=await db.get(Trace,body.trace_id)
    if not trace or trace.participant_id!=user.id: raise HTTPException(404,"Trace not found")
    await record_event(db,trace.id,body.event_type,body.payload,body.request_id,user.id,body.client_monotonic_ms)
    await db.commit()
    return {"accepted":True}

async def _persist_failure(request_id, trace_id, user_id, code, partial_text=""):
    async with SessionLocal() as db:
        row=await db.get(ChatRequest,request_id)
        if row:
            row.status="failed"; row.error_code=code; row.completed_at=utcnow()
            row.response_text=partial_text
            await record_event(db,trace_id,"request_failed",{"error_code":code,"partial_response_chars":len(partial_text)},request_id,user_id)
            await db.commit()

@app.post("/api/participant/prepare")
async def prepare_network_profile(body: PrepareIn, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role!="participant" or not user.consent_at or user.consent_version!=settings.consent_version:
        raise HTTPException(403,"Current study consent is required")
    assignment=await db.get(Assignment,body.assignment_id)
    trace=await db.get(Trace,body.trace_id)
    if not assignment or assignment.participant_id!=user.id or not trace or trace.participant_id!=user.id or trace.assignment_id!=assignment.id:
        raise HTTPException(404,"Assignment or trace not found")
    lock_name="qoe:gateway-network-profile"
    lock=redis_client.lock(lock_name,timeout=120,blocking=False)
    acquired=await lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(409,"The shared network-emulation gateway is currently reserved by another participant. Retry shortly.")
    prepared_key=f"qoe:prepared:{trace.id}"
    try:
        profile=(assignment.condition or {}).get("network_profile",{})
        ack=await apply_gateway_profile(profile)
        applied=bool(ack.get("applied", False)) if isinstance(ack,dict) else False
        has_impairment=any(float(profile.get(k,0) or 0) != 0
                           for k in ("latency_ms","jitter_ms","loss_pct","bandwidth_mbps"))
        if has_impairment and not applied:
            raise RuntimeError("GATEWAY_PROFILE_NOT_APPLIED")
        await redis_client.set(prepared_key,lock.token,ex=120)
        qdisc_start = ack.get("qdisc_counters") if isinstance(ack, dict) else None
        if qdisc_start:
            await redis_client.set(f"qoe:qdisc_start:{trace.id}", json.dumps(qdisc_start), ex=3600)
        await record_event(
            db,trace.id,
            "network_profile_applied" if applied else "baseline_only_no_gateway",
            {"network_profile":profile,"network_profile_applied":applied,
             "network_mode":"gateway-shaped" if applied else "baseline-only",
             "gateway_ack":ack,"qdisc_start_snapshot":qdisc_start,"lease_seconds":120},
            participant_id=user.id,
        )
        await db.commit()
        return {"prepared":True,"network_profile_applied":applied,
                "network_mode":"gateway-shaped" if applied else "baseline-only",
                "trace_id":trace.id,"lease_seconds":120}
    except Exception:
        await redis_client.delete(prepared_key)
        try: await lock.release()
        except RedisError: pass
        raise HTTPException(503,"Unable to prepare the assigned network profile")

@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role!="participant" or not user.consent_at or user.consent_version!=settings.consent_version:
        raise HTTPException(403,"Current study consent is required")
    if len(body.prompt)>settings.max_prompt_chars: raise HTTPException(413,"Prompt too long")
    assignment=await db.get(Assignment,body.assignment_id)
    trace=await db.get(Trace,body.trace_id)
    if not assignment or assignment.participant_id!=user.id or not trace or trace.participant_id!=user.id or trace.assignment_id!=assignment.id:
        raise HTTPException(404,"Assignment or trace not found")
    prepared_key=f"qoe:prepared:{trace.id}"
    lock_name="qoe:gateway-network-profile"
    lock_token=await redis_client.get(prepared_key)
    current_lock_token=await redis_client.get(lock_name)
    if not lock_token or lock_token!=current_lock_token:
        if not current_lock_token:
            try: await apply_gateway_profile({"latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0})
            except Exception: pass
        raise HTTPException(409,"Network profile lease missing or expired. Prepare the task again before sending.")
    arm=(assignment.condition or {}).get("model_arm","llm")
    base_url, model=(settings.llm_base_url,settings.llm_model) if arm=="llm" else (settings.slm_base_url,settings.slm_model)
    provider = settings.llm_provider if arm == "llm" else settings.slm_provider
    request_id=uid("req")
    row=ChatRequest(id=request_id,trace_id=trace.id,participant_id=user.id,prompt=body.prompt,
                    provider_model=model,status="queued")
    db.add(row)
    await record_event(db,trace.id,"request_queued",{"model_arm":arm,"provider":provider,"model":model,
        "network_profile":(assignment.condition or {}).get("network_profile",{})},request_id,user.id)
    await db.commit()
    network_lock_obj=redis_client.lock(lock_name,timeout=3600,token=lock_token)
    try:
        await network_lock_obj.extend(3600,replace_ttl=True)
    except RedisError:
        raise HTTPException(409,"Network profile lease expired; prepare the task again.")
    async def event_stream():
        start=time.perf_counter(); first=None; previous=None; gaps=[]; response_parts=[]; chunk_records=[]; response_bytes=0; response_chars=0; output_tokens=0; finish_reason=None
        try:
            await network_lock_obj.extend(3600,replace_ttl=True)
            yield f"event: metadata\ndata: {json.dumps({'request_id':request_id,'trace_id':trace.id,'provider':provider,'model':model,'model_arm':arm})}\n\n"
            queue_start=time.perf_counter()
            async with ACTIVE:
                queue_ms=(time.perf_counter()-queue_start)*1000
                async with SessionLocal() as session:
                    rr=await session.get(ChatRequest,request_id); rr.queue_time_ms=queue_ms; rr.status="running"
                    await record_event(session,trace.id,"inference_admitted",{"api_admission_queue_ms":queue_ms},request_id,user.id)
                    await session.commit()
                api_key=settings.llm_api_key if arm=="llm" else settings.slm_api_key
                payload={"model":model,"messages":[{"role":"user","content":body.prompt}],
                         "stream":True,"stream_options":{"include_usage":True},
                         "max_tokens":settings.max_output_tokens,"temperature":settings.temperature,"top_p":settings.top_p,"seed":settings.inference_seed}
                timeout=httpx.Timeout(connect=15,read=300,write=30,pool=15)
                provider_headers={"Content-Type":"application/json"}
                if api_key: provider_headers["Authorization"]=f"Bearer {api_key}"
                async with httpx.AsyncClient(timeout=timeout,verify=settings.inference_ca_bundle or True) as client:
                    async with client.stream("POST",base_url.rstrip("/")+"/chat/completions",
                        json=payload,headers=provider_headers) as resp:
                        if resp.status_code>=400:
                            text=(await resp.aread()).decode("utf-8","replace")[:1000]
                            raise RuntimeError(f"INFERENCE_HTTP_{resp.status_code}:{text}")
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"): continue
                            raw=line[5:].strip()
                            if raw=="[DONE]": break
                            try: packet=json.loads(raw)
                            except Exception: continue
                            if packet.get("usage"):
                                output_tokens=int(packet["usage"].get("completion_tokens") or output_tokens)
                            choices=packet.get("choices") or []
                            if not choices: continue
                            choice=choices[0]; delta=choice.get("delta") or {}
                            content=delta.get("content")
                            if content:
                                now=time.perf_counter()
                                if first is None:
                                    first=now; TTFT.observe(first-start)
                                    ttft_ms=(first-start)*1000
                                    async with SessionLocal() as session:
                                        rr=await session.get(ChatRequest,request_id)
                                        rr.ttft_ms=ttft_ms; rr.first_token_at=utcnow()
                                        await record_event(session,trace.id,"first_output_received",{"server_ttft_ms":ttft_ms},request_id,user.id)
                                        await session.commit()
                                if previous is not None: gaps.append((now-previous)*1000)
                                previous=now; response_parts.append(content)
                                chunk_bytes=len(content.encode("utf-8")); response_bytes+=chunk_bytes; response_chars+=len(content)
                                chunk_records.append({"sequence":len(chunk_records)+1,"arrival_ms":(now-start)*1000,
                                    "inter_event_gap_ms":gaps[-1] if gaps else None,"bytes":chunk_bytes,"characters":len(content)})
                                await network_lock_obj.extend(3600,replace_ttl=True)
                                yield f"event: delta\ndata: {json.dumps({'request_id':request_id,'text':content,'sequence':len(response_parts),'received_monotonic_ms':(now-start)*1000})}\n\n"
                            if choice.get("finish_reason"): finish_reason=choice["finish_reason"]
                end=time.perf_counter(); e2e=(end-start)*1000
                itl=(sum(gaps)/len(gaps)) if gaps else None
                tpot=(e2e-(first-start)*1000)/(max(output_tokens-1,1)) if first and output_tokens>1 else None
                STREAM_E2E.observe(e2e/1000)
                final_text="".join(response_parts)
                async with SessionLocal() as session:
                    rr=await session.get(ChatRequest,request_id)
                    rr.response_text=final_text; rr.status="completed"; rr.finish_reason=finish_reason
                    rr.e2e_latency_ms=e2e; rr.itl_mean_ms=itl; rr.tpot_ms=tpot
                    rr.output_tokens=output_tokens; rr.chunk_count=len(chunk_records)
                    rr.response_bytes=response_bytes; rr.response_chars=response_chars; rr.completed_at=utcnow()
                    await record_event(session,trace.id,"stream_chunk_summary",{
                        "chunk_count":len(chunk_records),"response_bytes":response_bytes,
                        "response_chars":response_chars,"chunk_events":chunk_records
                    },request_id,user.id)
                    await record_event(session,trace.id,"request_completed",{
                        "server_ttft_ms":rr.ttft_ms,"mean_inter_stream_event_gap_ms":itl,"tpot_ms":tpot,
                        "api_admission_queue_ms":rr.queue_time_ms,"server_e2e_latency_ms":e2e,
                        "output_tokens":output_tokens,"finish_reason":finish_reason,
                        "itl_measurement":"inter-SSE-output event gaps; token-level only when provider emits one token per event",
                        "tpot_measurement":"post-first-output stream duration divided by provider completion tokens minus one; includes transport/backpressure and is not pure engine TPOT"
                    },request_id,user.id)
                    await session.commit()
                yield f"event: completed\ndata: {json.dumps({'request_id':request_id,'trace_id':trace.id,'server_ttft_ms':(first-start)*1000 if first else None,'itl_mean_ms':itl,'tpot_ms':tpot,'queue_time_ms':queue_ms,'server_e2e_latency_ms':e2e,'output_tokens':output_tokens,'chunk_count':len(chunk_records),'response_bytes':response_bytes,'response_chars':response_chars,'finish_reason':finish_reason,'itl_measurement':'inter-SSE-output event gaps; token-level only when provider emits one token per event','tpot_measurement':'end-to-end post-first-output estimate, not pure engine TPOT','status':'completed'})}\n\n"
        except asyncio.CancelledError:
            await _persist_failure(request_id,trace.id,user.id,"CLIENT_CANCELLED","".join(response_parts))
            raise
        except Exception as exc:
            code=str(exc).split(":")[0][:80]
            await _persist_failure(request_id,trace.id,user.id,code,"".join(response_parts))
            yield f"event: error\ndata: {json.dumps({'request_id':request_id,'trace_id':trace.id,'error':'Inference request failed','error_code':code})}\n\n"
        finally:
            current_token=await redis_client.get(lock_name)
            if current_token==lock_token:
                end_stats=None; status_error=None
                try: end_stats=await get_gateway_status()
                except Exception as exc: status_error=type(exc).__name__
                try:
                    start_raw = await redis_client.get(f"qoe:qdisc_start:{trace.id}")
                    start_snapshot = json.loads(start_raw) if start_raw else None
                    end_snapshot = end_stats.get("qdisc_counters") if isinstance(end_stats, dict) else None
                    qdisc_measurement = calculate_qdisc_deltas(start_snapshot, end_snapshot)
                    async with SessionLocal() as session:
                        event_type = "network_qdisc_measurement" if qdisc_measurement.get("available") else "network_qdisc_measurement_unavailable"
                        await record_event(session,trace.id,event_type,
                            {**qdisc_measurement,"start_snapshot":start_snapshot,"end_snapshot":end_snapshot,
                             "gateway_status_error":status_error,
                             "measurement_window":"profile_applied_to_stream_end_before_baseline_reset"},request_id,user.id)
                        await session.commit()
                except Exception as measurement_error:
                    try:
                        async with SessionLocal() as session:
                            await record_event(session,trace.id,"network_qdisc_measurement_failed",
                                {"error_type":type(measurement_error).__name__,"gateway_status_error":status_error},request_id,user.id)
                            await session.commit()
                    except Exception:
                        pass
                try:
                    reset_ack=await apply_gateway_profile({"latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0})
                    async with SessionLocal() as session:
                        await record_event(session,trace.id,"network_profile_reset",
                            {"profile":"baseline","gateway_end_stats":end_stats,"gateway_status_error":status_error,
                             "gateway_reset_ack":reset_ack},request_id,user.id)
                        await session.commit()
                except Exception as reset_error:
                    try:
                        async with SessionLocal() as session:
                            await record_event(session,trace.id,"network_profile_reset_failed",
                                {"error_type":type(reset_error).__name__,"gateway_status_error":status_error},request_id,user.id)
                            await session.commit()
                    except Exception:
                        pass
                finally:
                    try:
                        await redis_client.delete(f"qoe:qdisc_start:{trace.id}")
                        await redis_client.delete(prepared_key)
                    except RedisError:
                        pass
                    try: await network_lock_obj.release()
                    except RedisError: pass
            else:
                await redis_client.delete(prepared_key)
    return StreamingResponse(event_stream(),media_type="text/event-stream",
        headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no","X-Request-ID":request_id,"X-Trace-ID":trace.id})

@app.get("/api/protocol/consent")
async def consent_information():
    return {**CONSENT_SUMMARY,"version":settings.consent_version}

@app.post("/api/participant/consent")
async def accept_consent(body: ConsentIn, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role!="participant": raise HTTPException(403,"Participant role required")
    if not body.accepted: raise HTTPException(422,"Explicit consent acceptance is required")
    if body.consent_version!=settings.consent_version: raise HTTPException(409,"Consent version changed; reload the consent page")
    user.consent_at=utcnow(); user.consent_version=body.consent_version
    await db.commit()
    return {"accepted":True,"consent_version":user.consent_version,"consent_at":user.consent_at.isoformat()}

@app.post("/api/participant/withdraw")
async def withdraw_participation(response: Response, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role!="participant": raise HTTPException(403,"Participant role required")
    user.active=False; user.consent_withdrawn_at=utcnow()
    await db.commit()
    response.delete_cookie("qoe_access",path="/")
    response.delete_cookie("qoe_csrf",path="/")
    return {"withdrawn":True,"message":"Further study access is disabled. Data retention/deletion follows the approved consent and institutional policy."}

@app.get("/api/protocol/questionnaires")
async def questionnaires(user: User=Depends(current_user)):
    return {"nasa_tlx":NASA_TLX,"p852_aligned_qoe":P852_QOE}

@app.post("/api/participant/questionnaires",status_code=201)
async def submit_questionnaire(body: QuestionnaireIn, db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    trace=await db.get(Trace,body.trace_id)
    if not trace or trace.participant_id!=user.id: raise HTTPException(404,"Trace not found")
    if body.instrument=="nasa_tlx_raw":
        keys=[x["key"] for x in NASA_TLX["dimensions"]]
        if set(body.answers)!=set(keys): raise HTTPException(422,"All six NASA-TLX ratings are required")
        vals=[float(body.answers[k]) for k in keys]
        if any(v<0 or v>100 for v in vals): raise HTTPException(422,"NASA-TLX ratings must be 0–100")
        score=sum(vals)/6
    elif body.instrument=="p852_aligned_supplemental":
        keys=[x["key"] for x in P852_QOE["items"]]
        if set(body.answers)!=set(keys): raise HTTPException(422,"All QoE items are required")
        vals=[int(body.answers[k]) for k in keys]
        if any(v<1 or v>5 for v in vals): raise HTTPException(422,"QoE ratings must be 1–5")
        score=sum(vals)/len(vals)
    else: raise HTTPException(422,"Unknown instrument")
    db.add(Questionnaire(trace_id=trace.id,participant_id=user.id,instrument=body.instrument,answers=body.answers,score=score))
    await record_event(db,trace.id,"questionnaire_submitted",{"instrument":body.instrument,"score":score},participant_id=user.id)
    await db.flush()
    completed_instruments=(await db.scalars(select(Questionnaire.instrument).where(Questionnaire.trace_id==trace.id))).all()
    if {"nasa_tlx_raw","p852_aligned_supplemental"}.issubset(set(completed_instruments)):
        assignment=await db.get(Assignment,trace.assignment_id)
        assignment.status="completed"; assignment.completed_at=utcnow()
    await db.commit()
    return {"accepted":True,"instrument":body.instrument,"score":score}

@app.post("/api/admin/scorers",status_code=201)
async def create_scorer(body: ParticipantCreate, db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    if await db.scalar(select(User).where(User.username==body.username)):
        raise HTTPException(409,"Username already exists")
    user=User(username=body.username,password_hash=hash_password(body.password),role="scorer",
              participant_code=f"S-{uuid.uuid4().hex[:10].upper()}",active=True)
    db.add(user); await db.commit(); await db.refresh(user)
    return {"id":user.id,"username":user.username,"role":"scorer"}

@app.post("/api/admin/rubric-scores",status_code=201)
async def score_rubric(body: RubricScoreIn, db: AsyncSession=Depends(get_db), admin: User=Depends(current_user)):
    if admin.role not in {"admin","scorer"}: raise HTTPException(403,"Scorer role required")
    trace=await db.get(Trace,body.trace_id)
    if not trace: raise HTTPException(404,"Trace not found")
    task=await db.get(Task,trace.task_id)
    existing=await db.scalar(select(RubricScore).where(RubricScore.trace_id==trace.id,RubricScore.scorer_id==admin.id))
    if existing: raise HTTPException(409,"This scorer has already rated this trace")
    criteria={x["criterion"]:x["weight"] for x in task.rubric}
    if set(body.criterion_scores)!=set(criteria): raise HTTPException(422,"Scores must cover every rubric criterion")
    if any(not 0<=float(v)<=100 for v in body.criterion_scores.values()): raise HTTPException(422,"Each criterion score must be 0–100")
    weighted=sum(float(body.criterion_scores[k])*criteria[k] for k in criteria)/sum(criteria.values())
    row=RubricScore(trace_id=trace.id,scorer_id=admin.id,criterion_scores=body.criterion_scores,total_score=weighted,blinded=True)
    db.add(row); await db.commit()
    return {"score_id":row.id,"weighted_score":weighted}

@app.post("/api/admin/gateway/reset")
async def reset_gateway(admin: User=Depends(admin_user)):
    lock=redis_client.lock("qoe:gateway-network-profile",timeout=30,blocking=False)
    if not await lock.acquire(blocking=False):
        raise HTTPException(409,"Gateway is currently leased by a participant request")
    try:
        ack=await apply_gateway_profile({"latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0})
        applied=bool(ack.get("applied", True)) if isinstance(ack,dict) else True
        return {"reset":applied,"profile":"baseline","gateway_ack":ack}
    finally:
        try: await lock.release()
        except RedisError: pass

@app.get("/api/admin/deployment-status")
async def admin_deployment_status(admin: User=Depends(admin_user)):
    gateway_configured = bool(settings.gateway_control_url and settings.gateway_token)
    gateway_status = None
    gateway_error = None
    if gateway_configured:
        try:
            gateway_status = await get_gateway_status()
        except Exception as exc:
            gateway_error = type(exc).__name__
    return {
        "gateway_configured": gateway_configured,
        "network_impairment_enabled": gateway_configured and gateway_status is not None,
        "network_mode": "gateway-controlled" if gateway_configured else "baseline-only",
        "require_gateway": settings.require_gateway,
        "gateway_status": gateway_status,
        "gateway_status_error": gateway_error,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "slm_provider": settings.slm_provider,
        "slm_model": settings.slm_model,
    }

@app.get("/api/admin/summary")
async def admin_summary(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    return {
      "participants":await db.scalar(select(func.count(User.id)).where(User.role=="participant")),
      "experiments":await db.scalar(select(func.count(Experiment.id))),
      "assignments":await db.scalar(select(func.count(Assignment.id))),
      "traces":await db.scalar(select(func.count(Trace.id))),
      "requests":await db.scalar(select(func.count(ChatRequest.id))),
      "questionnaires":await db.scalar(select(func.count(Questionnaire.id)))
    }

@app.get("/api/admin/analytics")
async def admin_analytics(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    request_rows = (await db.execute(
        select(ChatRequest, Trace, Assignment)
        .join(Trace, ChatRequest.trace_id == Trace.id)
        .join(Assignment, Trace.assignment_id == Assignment.id)
        .order_by(ChatRequest.started_at)
    )).all()
    ttft = [float(r.ttft_ms) for r, _, _ in request_rows if r.ttft_ms is not None]
    e2e = [float(r.e2e_latency_ms) for r, _, _ in request_rows if r.e2e_latency_ms is not None]
    rates = [float(r.output_tokens) / (float(r.e2e_latency_ms) / 1000.0)
             for r, _, _ in request_rows if r.output_tokens and r.e2e_latency_ms and r.e2e_latency_ms > 0]
    groups = {}
    for req, trace, assignment in request_rows:
        condition = (assignment.condition or {}).get("network_profile", {}).get("name", "unspecified")
        bucket = groups.setdefault(condition, {"ttft": [], "e2e": [], "rates": [], "requests": 0})
        bucket["requests"] += 1
        if req.ttft_ms is not None: bucket["ttft"].append(float(req.ttft_ms))
        if req.e2e_latency_ms is not None: bucket["e2e"].append(float(req.e2e_latency_ms))
        if req.output_tokens and req.e2e_latency_ms and req.e2e_latency_ms > 0:
            bucket["rates"].append(float(req.output_tokens) / (float(req.e2e_latency_ms) / 1000.0))
    qrows = (await db.scalars(select(Questionnaire))).all()
    probe_events = (await db.scalars(select(Event).where(Event.event_type == "https_rtt_probe"))).all()
    rtt_values = [float((event.payload or {}).get("rtt_ms")) for event in probe_events
                  if isinstance((event.payload or {}).get("rtt_ms"), (int, float))]
    rtt_mean = round(sum(rtt_values) / len(rtt_values), 2) if rtt_values else None
    rtt_sd = None
    if len(rtt_values) > 1:
        rtt_sd = round((sum((value - sum(rtt_values) / len(rtt_values)) ** 2 for value in rtt_values) / len(rtt_values)) ** 0.5, 2)
    distribution = {}
    for questionnaire in qrows:
        if questionnaire.instrument not in {"p852_aligned_supplemental", "qoe"}:
            continue
        for key, value in (questionnaire.answers or {}).items():
            if isinstance(value, (int, float)):
                distribution.setdefault(key, []).append(float(value))
    def mean(values):
        return round(sum(values) / len(values), 2) if values else None
    return {
        "summary": {
            "participants": await db.scalar(select(func.count(User.id)).where(User.role == "participant")),
            "experiments": await db.scalar(select(func.count(Experiment.id))),
            "assignments": await db.scalar(select(func.count(Assignment.id))),
            "traces": await db.scalar(select(func.count(Trace.id))),
            "requests": len(request_rows),
            "questionnaires": len(qrows),
        },
        "completed_requests": sum(1 for r, _, _ in request_rows if r.status == "completed"),
        "mean_ttft_ms": mean(ttft),
        "mean_e2e_ms": mean(e2e),
        "mean_tokens_per_second": mean(rates),
        "mean_https_rtt_ms": rtt_mean,
        "https_rtt_variation_sd_ms": rtt_sd,
        "https_rtt_probe_samples": len(rtt_values),
        "by_network": [{
            "condition": name, "requests": data["requests"],
            "mean_ttft_ms": mean(data["ttft"]), "mean_e2e_ms": mean(data["e2e"]),
            "mean_tokens_per_second": mean(data["rates"])
        } for name, data in sorted(groups.items())],
        "qoe_distribution": {key: mean(values) for key, values in distribution.items()},
        "measurement_note": "Server TTFT includes API admission-queue wait. Output rate is estimated from recorded output_tokens divided by end-to-end latency; it is not provider-authoritative. HTTPS RTT probes measure browser-to-lab health-endpoint round trips, not packet-level jitter or RTT to the LLM provider."
    }


@app.get("/api/admin/export/study.xlsx")
async def export_study_workbook(
    experiment_id: str | None = None,
    task_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(admin_user)
):
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from fastapi.responses import Response

    traces = (await db.scalars(select(Trace).order_by(Trace.started_at))).all()
    if experiment_id:
        traces = [t for t in traces if t.experiment_id == experiment_id]
    if task_id:
        traces = [t for t in traces if t.task_id == task_id]
    trace_ids = {t.id for t in traces}
    people = (await db.scalars(select(User))).all()
    participant_codes = {u.id: (u.participant_code or "STAFF") for u in people}
    requests = (await db.scalars(select(ChatRequest).order_by(ChatRequest.started_at))).all()
    requests = [r for r in requests if r.trace_id in trace_ids]
    events = (await db.scalars(select(Event).order_by(Event.occurred_at))).all()
    events = [e for e in events if e.trace_id in trace_ids]
    questionnaires = (await db.scalars(select(Questionnaire).order_by(Questionnaire.submitted_at))).all()
    questionnaires = [q for q in questionnaires if q.trace_id in trace_ids]

    wb = Workbook()
    ws = wb.active
    ws.title = "Requests"
    qdisc_events = {e.request_id: (e.payload or {}) for e in events
                    if e.event_type == "network_qdisc_measurement" and e.request_id}
    ws.append(["request_id", "trace_id", "participant_code", "model", "status", "participant_prompt",
               "participant_prompt_chars", "AI_response", "AI_response_chars", "TTFT_ms",
               "ITL_mean_ms", "TPOT_ms", "queue_time_ms", "E2E_ms", "output_tokens",
               "chunk_count", "response_bytes", "finish_reason", "WAN_qdisc_deltas_json",
               "IFB_qdisc_deltas_json", "qdisc_measurement_window", "started_at", "completed_at"])
    for req in requests:
        trace = next((t for t in traces if t.id == req.trace_id), None)
        ws.append([req.id, req.trace_id, participant_codes.get(req.participant_id, "UNKNOWN"),
                   req.provider_model, req.status, req.prompt, len(req.prompt or ""), req.response_text,
                   req.response_chars, req.ttft_ms, req.itl_mean_ms, req.tpot_ms,
                   req.queue_time_ms, req.e2e_latency_ms, req.output_tokens, req.chunk_count,
                   req.response_bytes, req.finish_reason,
                   json.dumps(qdisc_events.get(req.id, {}).get("wan_qdisc_deltas"), ensure_ascii=False),
                   json.dumps(qdisc_events.get(req.id, {}).get("ifb_qdisc_deltas"), ensure_ascii=False),
                   qdisc_events.get(req.id, {}).get("measurement_window"),
                   req.started_at.isoformat() if req.started_at else None,
                   req.completed_at.isoformat() if req.completed_at else None])
    ev = wb.create_sheet("Event Ledger")
    ev.append(["event_id", "trace_id", "request_id", "participant_code", "event_type", "occurred_at", "client_monotonic_ms", "payload_json"])
    for event in events:
        ev.append([event.id, event.trace_id, event.request_id,
                   participant_codes.get(event.participant_id, "UNKNOWN"), event.event_type,
                   event.occurred_at.isoformat() if event.occurred_at else None,
                   event.client_monotonic_ms, json.dumps(event.payload or {}, ensure_ascii=False)])
    qws = wb.create_sheet("Questionnaires")
    qws.append(["questionnaire_id", "trace_id", "participant_code", "instrument", "answers_json", "score", "submitted_at"])
    for q in questionnaires:
        qws.append([q.id, q.trace_id, participant_codes.get(q.participant_id, "UNKNOWN"),
                    q.instrument, json.dumps(q.answers or {}, ensure_ascii=False), q.score,
                    q.submitted_at.isoformat() if q.submitted_at else None])
    snapshots = (await db.scalars(select(ModelSnapshot).order_by(ModelSnapshot.experiment_id, ModelSnapshot.arm))).all()
    if experiment_id:
        snapshots = [s for s in snapshots if s.experiment_id == experiment_id]
    provenance = wb.create_sheet("Model Provenance")
    provenance.append(["experiment_id", "arm", "provider", "model_id", "repository", "revision",
                       "engine_version", "provenance_status", "weights_immutable", "config_sha256", "frozen_at"])
    for snap in snapshots:
        provenance.append([snap.experiment_id, snap.arm, snap.provider, snap.model_id, snap.repository,
                           snap.revision, snap.engine_version, (snap.config or {}).get("provenance_status"),
                           (snap.config or {}).get("weights_immutable"), snap.config_sha256,
                           snap.frozen_at.isoformat() if snap.frozen_at else None])
    manifest = wb.create_sheet("Export Manifest")
    manifest.append(["field", "value"])
    manifest.append(["exported_at_utc", utcnow().isoformat()])
    manifest.append(["experiment_id_filter", experiment_id or "ALL"])
    manifest.append(["task_id_filter", task_id or "ALL"])
    manifest.append(["trace_rows", len(traces)])
    manifest.append(["request_rows", len(requests)])
    manifest.append(["event_rows", len(events)])
    manifest.append(["questionnaire_rows", len(questionnaires)])
    manifest.append(["privacy", "Participant codes are pseudonymous; workbook includes prompt and AI response text. Restrict access and follow consent/data-retention rules."])
    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="26364A")
        for column in sheet.columns:
            letter = column[0].column_letter
            width = min(42, max(12, max(len(str(c.value or "")) for c in column[:200]) + 2))
            sheet.column_dimensions[letter].width = width
    output = BytesIO()
    wb.save(output)
    suffix = f"-{experiment_id}" if experiment_id else ""
    return Response(output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="llm-qoe-research{suffix}.xlsx"'})


@app.get("/api/scorer/queue")
async def scorer_queue(db: AsyncSession=Depends(get_db), user: User=Depends(current_user)):
    if user.role not in {"admin","scorer"}: raise HTTPException(403,"Scorer role required")
    scored=(await db.scalars(select(RubricScore.trace_id).where(RubricScore.scorer_id==user.id))).all()
    rows=(await db.execute(select(Trace,Task,ChatRequest).join(Task,Task.id==Trace.task_id)
        .join(ChatRequest,ChatRequest.trace_id==Trace.id).where(ChatRequest.status=="completed")
        .order_by(Trace.started_at,ChatRequest.started_at))).all()
    latest={}
    for trace,task,req in rows:
        latest[trace.id]=(trace,task,req)
    return [{"trace_id":trace.id,"task_code":task.task_code,"task_title":task.title,
        "task_prompt":task.prompt,"rubric":task.rubric,"response_text":req.response_text,"request_id":req.id}
        for trace,task,req in latest.values() if trace.id not in set(scored)]

@app.get("/api/admin/export/events.jsonl")
async def export_events(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    rows=(await db.scalars(select(Event).order_by(Event.occurred_at))).all()
    people=(await db.scalars(select(User))).all()
    code_map={u.id:(u.participant_code or "STAFF") for u in people}
    content="".join(json.dumps({"event_id":e.id,"trace_id":e.trace_id,"request_id":e.request_id,
      "participant_id":code_map.get(e.participant_id,"UNKNOWN"),"event_type":e.event_type,"occurred_at":e.occurred_at.isoformat(),
      "client_monotonic_ms":e.client_monotonic_ms,"payload":e.payload},ensure_ascii=False)+"\n" for e in rows)
    from fastapi.responses import Response
    return Response(content,media_type="application/x-ndjson",headers={"Content-Disposition":"attachment; filename=llm-qoe-events.jsonl"})

@app.get("/api/admin/export/study.json")
async def export_study(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    traces=(await db.scalars(select(Trace).order_by(Trace.started_at))).all()
    qdisc_events=(await db.scalars(select(Event).where(Event.event_type=="network_qdisc_measurement"))).all()
    qdisc_by_request={e.request_id:(e.payload or {}) for e in qdisc_events if e.request_id}
    result=[]
    for trace in traces:
        task=await db.get(Task,trace.task_id)
        assignment=await db.get(Assignment,trace.assignment_id)
        experiment=await db.get(Experiment,trace.experiment_id)
        participant=await db.get(User,trace.participant_id)
        snapshot=await db.scalar(select(ModelSnapshot).where(
            ModelSnapshot.experiment_id==trace.experiment_id,ModelSnapshot.arm==trace.model_arm))
        requests=(await db.scalars(select(ChatRequest).where(ChatRequest.trace_id==trace.id))).all()
        questionnaires=(await db.scalars(select(Questionnaire).where(Questionnaire.trace_id==trace.id))).all()
        scores=(await db.scalars(select(RubricScore).where(RubricScore.trace_id==trace.id))).all()
        result.append({"trace":{"id":trace.id,"experiment_id":trace.experiment_id,"task_id":trace.task_id,
            "assignment_id":trace.assignment_id,"participant_id":participant.participant_code if participant else "UNKNOWN",
            "consent_version":participant.consent_version if participant else None,
            "consent_withdrawn_at":participant.consent_withdrawn_at.isoformat() if participant and participant.consent_withdrawn_at else None,
            "model_arm":trace.model_arm,
            "started_at":trace.started_at.isoformat()},
            "experiment":{"name":experiment.name,"protocol_version":experiment.protocol_version,"seed":experiment.seed,
                "ethics_approved":experiment.ethics_approved,"ethics_approval_ref":experiment.ethics_approval_ref,
                "ethics_approved_at":experiment.ethics_approved_at.isoformat() if experiment.ethics_approved_at else None},
            "task":{"task_code":task.task_code,"title":task.title,"rubric":task.rubric},
            "assignment":{"sequence_no":assignment.sequence_no,"condition":assignment.condition},
            "model_snapshot":{"arm":snapshot.arm,"provider":snapshot.provider,"model_id":snapshot.model_id,
                "repository":snapshot.repository,"revision":snapshot.revision,"engine_version":snapshot.engine_version,
                "config":snapshot.config,"config_sha256":snapshot.config_sha256,
                "frozen_at":snapshot.frozen_at.isoformat() if snapshot.frozen_at else None} if snapshot else None,
            "requests":[{"id":r.id,"model":r.provider_model,"status":r.status,"prompt":r.prompt,
                "response_text":r.response_text,"ttft_ms":r.ttft_ms,"itl_mean_ms":r.itl_mean_ms,
                "tpot_ms":r.tpot_ms,"queue_time_ms":r.queue_time_ms,"e2e_latency_ms":r.e2e_latency_ms,
                "output_tokens":r.output_tokens,"chunk_count":r.chunk_count,"response_bytes":r.response_bytes,
                "response_chars":r.response_chars,"finish_reason":r.finish_reason,
                "qdisc_measurement":qdisc_by_request.get(r.id)} for r in requests],
            "questionnaires":[{"instrument":q.instrument,"answers":q.answers,"score":q.score} for q in questionnaires],
            "rubric_scores":[{"criterion_scores":r.criterion_scores,"total_score":r.total_score,
                "scorer_id":(await db.get(User,r.scorer_id)).participant_code if await db.get(User,r.scorer_id) else "UNKNOWN"} for r in scores]})
    return JSONResponse(result,headers={"Content-Disposition":"attachment; filename=llm-qoe-study-export.json"})

@app.get("/api/admin/export/requests.csv")
async def export_requests(db: AsyncSession=Depends(get_db), admin: User=Depends(admin_user)):
    rows=(await db.scalars(select(ChatRequest).order_by(ChatRequest.started_at))).all()
    people=(await db.scalars(select(User))).all()
    code_map={u.id:(u.participant_code or "STAFF") for u in people}
    import csv,io
    buf=io.StringIO(); writer=csv.writer(buf)
    qdisc_events = (await db.scalars(select(Event).where(Event.event_type == "network_qdisc_measurement"))).all()
    qdisc_by_request = {e.request_id: (e.payload or {}) for e in qdisc_events if e.request_id}
    writer.writerow(["request_id","trace_id","participant_id","model","status","participant_prompt_chars","ai_response_chars","ttft_ms","itl_mean_ms","tpot_ms","queue_time_ms","e2e_latency_ms","output_tokens","chunk_count","response_bytes","finish_reason","wan_qdisc_deltas_json","ifb_qdisc_deltas_json","qdisc_measurement_window","started_at","completed_at"])
    for r in rows:
        q = qdisc_by_request.get(r.id, {})
        writer.writerow([r.id,r.trace_id,code_map.get(r.participant_id,"UNKNOWN"),r.provider_model,r.status,len(r.prompt or ""),r.response_chars,r.ttft_ms,r.itl_mean_ms,r.tpot_ms,r.queue_time_ms,r.e2e_latency_ms,r.output_tokens,r.chunk_count,r.response_bytes,r.finish_reason,json.dumps(q.get("wan_qdisc_deltas"),ensure_ascii=False),json.dumps(q.get("ifb_qdisc_deltas"),ensure_ascii=False),q.get("measurement_window"),r.started_at,r.completed_at])
    from fastapi.responses import Response
    return Response(buf.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=llm-qoe-requests.csv"})
