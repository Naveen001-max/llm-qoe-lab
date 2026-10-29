import os, json, time, asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
BASE_URL = os.getenv('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')
DEFAULT_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
FALLBACK_MODELS = [m.strip() for m in os.getenv('GEMINI_FALLBACK_MODELS', 'gemini-3.5-flash-lite,gemini-3.6-flash').split(',') if m.strip()]
LLM_HTTP_PROXY = os.getenv('LLM_HTTP_PROXY', '').strip()
NETEM_CONTROL_URL = os.getenv('NETEM_CONTROL_URL', '').rstrip('/')

app = FastAPI(title='LLM Network & QoE Monitoring Lab', version='3.2.0')
app.mount('/static', StaticFiles(directory=os.path.join(APP_DIR, 'static')), name='static')

class ChatRequest(BaseModel):
    messages: list[dict] = Field(min_length=1)
    model: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    output_rate_tps: int = Field(default=40, ge=1, le=200)

class ProbeRequest(BaseModel):
    target: str = 'https://www.google.com/generate_204'
    count: int = Field(default=3, ge=1, le=10)

class EmulationRequest(BaseModel):
    latency_ms: int = Field(default=0, ge=0, le=250)
    jitter_ms: int = Field(default=0, ge=0, le=40)
    loss_pct: float = Field(default=0, ge=0, le=3)

@app.get('/')
def index():
    return FileResponse(os.path.join(APP_DIR, 'static', 'index.html'))

@app.get('/api/status')
async def status():
    emulation = await get_emulation_status()
    return {'configured': bool(API_KEY), 'model': DEFAULT_MODEL, 'base_url': BASE_URL,
            'provider': 'Google Gemini API', 'server_time': datetime.now(timezone.utc).isoformat(),
            'network_emulation': emulation, 'proxy_configured': bool(LLM_HTTP_PROXY)}

async def get_emulation_status():
    if not NETEM_CONTROL_URL:
        return {'available': False, 'ready': False, 'mode': 'unavailable',
                'message': 'Real network emulation is not configured. Start with Docker Compose.'}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(NETEM_CONTROL_URL + '/status')
            d = r.json()
            d['available'] = True
            d['mode'] = 'real-linux-tc-netem' if d.get('ready') else 'error'
            return d
    except Exception as e:
        return {'available': True, 'ready': False, 'mode': 'error', 'error': str(e),
                'message': 'Network emulator control service is unreachable.'}

@app.get('/api/emulation')
async def emulation_status():
    return await get_emulation_status()

@app.get('/api/network-stats')
async def network_stats():
    if not NETEM_CONTROL_URL:
        return {'available': False, 'message': 'Real packet counters require Docker/Linux NetEm.'}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(NETEM_CONTROL_URL + '/stats')
            data = r.json()
            data['available'] = r.status_code == 200
            return data
    except Exception as e:
        return {'available': False, 'error': str(e), 'at': datetime.now(timezone.utc).isoformat()}

@app.post('/api/emulation')
async def update_emulation(req: EmulationRequest):
    if not NETEM_CONTROL_URL or not LLM_HTTP_PROXY:
        raise HTTPException(status_code=503, detail='Real traffic shaping is unavailable in native Windows mode. Start this project with Docker Compose so LLM traffic is routed through the Linux network emulator.')
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(NETEM_CONTROL_URL + '/settings', json=req.model_dump())
            data = r.json()
            if r.status_code >= 400 or not data.get('ok'):
                raise HTTPException(status_code=503, detail=data.get('error', 'Linux traffic shaping failed'))
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f'Could not apply real network settings: {e}')

@app.post('/api/chat/stream')
async def chat_stream(req: ChatRequest):
    if not API_KEY:
        raise HTTPException(status_code=503, detail='Gemini API key is not configured. Set GEMINI_API_KEY in your environment or .env setup instructions, then restart the server.')
    model = (req.model or DEFAULT_MODEL).strip()

    # Convert the browser's OpenAI-style conversation history into Gemini contents.
    contents = []
    system_instructions = []
    for message in req.messages:
        role = str(message.get('role', 'user')).lower()
        text_content = message.get('content', '')
        if not isinstance(text_content, str):
            text_content = str(text_content)
        if role == 'system':
            system_instructions.append(text_content)
            continue
        gemini_role = 'model' if role in ('assistant', 'model') else 'user'
        if contents and contents[-1]['role'] == gemini_role:
            contents[-1]['parts'][0]['text'] += '\n' + text_content
        else:
            contents.append({'role': gemini_role, 'parts': [{'text': text_content}]})
    if not contents:
        raise HTTPException(status_code=400, detail='At least one user message is required.')
    payload = {'contents': contents, 'generationConfig': {'temperature': req.temperature}}
    if system_instructions:
        payload['systemInstruction'] = {'parts': [{'text': '\n'.join(system_instructions)}]}

    async def events():
        started = time.perf_counter()
        output_has_started = False
        requested_models = []
        for candidate in [model, *FALLBACK_MODELS]:
            if candidate and candidate not in requested_models:
                requested_models.append(candidate)
        upstream_payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        upstream_content_parts = sum(len(item.get('parts', [])) for item in contents)
        yield 'event: meta\ndata: ' + json.dumps({'model': model, 'provider': 'Google Gemini API', 'server_started_at': datetime.now(timezone.utc).isoformat(), 'fallback_enabled': True, 'output_rate_tps': req.output_rate_tps, 'upstream_request_payload_bytes': upstream_payload_bytes, 'upstream_content_parts_sent': upstream_content_parts, 'request_semantics': 'One Gemini generate-content request with conversation content parts; response stream chunks are generated by Gemini and returned to the client.'}) + '\n\n'
        timeout = httpx.Timeout(connect=20.0, read=180.0, write=30.0, pool=20.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, proxy=LLM_HTTP_PROXY or None) as client:
                last_error = None
                for model_index, active_model in enumerate(requested_models):
                    # Retry transient provider overloads with bounded exponential backoff.
                    for attempt in range(3):
                        url = f"{BASE_URL}/models/{active_model}:streamGenerateContent?alt=sse&key={API_KEY}"
                        async with client.stream('POST', url, headers={'Content-Type': 'application/json'}, json=payload) as response:
                            if response.status_code >= 400:
                                body = (await response.aread()).decode('utf-8', errors='replace')[:2000]
                                try:
                                    parsed = json.loads(body)
                                    body = parsed.get('error', {}).get('message', body)
                                    status_code = parsed.get('error', {}).get('code', response.status_code)
                                except Exception:
                                    status_code = response.status_code
                                last_error = {'status': status_code, 'message': body, 'model': active_model}
                                transient = status_code in (500, 502, 503, 504)
                                if transient and attempt < 2:
                                    delay = 1.0 * (2 ** attempt)
                                    yield 'event: retry\ndata: ' + json.dumps({'model': active_model, 'attempt': attempt + 1, 'max_attempts': 3, 'retry_in_seconds': delay, 'reason': body, 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
                                    await asyncio.sleep(delay)
                                    continue
                                # Try a different configured model after overload/server errors.
                                if transient and model_index < len(requested_models) - 1:
                                    yield 'event: fallback\ndata: ' + json.dumps({'from_model': active_model, 'to_model': requested_models[model_index + 1], 'reason': body, 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
                                    break
                                # 429/quota, invalid model, or auth errors should be reported clearly.
                                friendly = body
                                if status_code == 429:
                                    friendly = 'Gemini API rate/quota limit reached (HTTP 429). Check your Google AI Studio quota and billing; retrying another model may not bypass project-level quota limits. Details: ' + body
                                elif status_code in (401, 403):
                                    friendly = 'Gemini API authentication/permission failed. Check GEMINI_API_KEY and model access. Details: ' + body
                                elif transient:
                                    friendly = 'Gemini models are temporarily unavailable after retries and fallback attempts. Please try again shortly. Last provider error: ' + body
                                yield 'event: error\ndata: ' + json.dumps({'status': status_code, 'message': friendly, 'model': active_model, 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
                                return
                            # Successful HTTP response: report the actual model selected and stream tokens.
                            if active_model != model:
                                yield 'event: model_selected\ndata: ' + json.dumps({'requested_model': model, 'active_model': active_model, 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
                            async for line in response.aiter_lines():
                                if not line or not line.startswith('data:'):
                                    continue
                                data = line[5:].strip()
                                try:
                                    obj = json.loads(data)
                                    candidates = obj.get('candidates') or []
                                    parts = ((candidates[0].get('content') or {}).get('parts') or []) if candidates else []
                                    for part in parts:
                                        delta = part.get('text')
                                        if delta:
                                            # Application-level output pacing. This caps delivery rate to the client; it does not change Gemini's internal inference speed.
                                            estimated_tokens = max(1, round(len(delta) / 4))
                                            pacing_delay = min(estimated_tokens / max(1, req.output_rate_tps), 5.0)
                                            # Keep the first delta immediate so TTFT remains a useful first-response metric.
                                            if output_has_started and pacing_delay > 0:
                                                await asyncio.sleep(pacing_delay)
                                            yield 'event: token\ndata: ' + json.dumps({'text': delta, 'at': datetime.now(timezone.utc).isoformat(), 'model': active_model, 'estimated_tokens': estimated_tokens, 'output_rate_tps': req.output_rate_tps}) + '\n\n'
                                            output_has_started = True
                                    finish = candidates[0].get('finishReason') if candidates else None
                                    if finish and finish not in ('STOP', 'MAX_TOKENS'):
                                        yield 'event: provider_notice\ndata: ' + json.dumps({'finish_reason': finish, 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
                                except json.JSONDecodeError:
                                    continue
                            yield 'event: done\ndata: ' + json.dumps({'model': active_model, 'server_elapsed_ms': round((time.perf_counter()-started)*1000, 2), 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
                            return
                        # The inner loop's break means try the next fallback model.
                        if last_error and attempt == 2 and last_error.get('model') == active_model:
                            break
                yield 'event: error\ndata: ' + json.dumps({'message': 'No configured Gemini model could serve this request. Check model availability and API quota.', 'last_error': last_error, 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
        except Exception as e:
            yield 'event: error\ndata: ' + json.dumps({'message': 'Could not reach the Gemini API or controlled network proxy. Check connectivity and proxy status. Details: ' + str(e), 'at': datetime.now(timezone.utc).isoformat()}) + '\n\n'
    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control':'no-cache', 'X-Accel-Buffering':'no'})

@app.post('/api/network-probe')
async def network_probe(req: ProbeRequest):
    results=[]
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, proxy=LLM_HTTP_PROXY or None) as client:
        for i in range(req.count):
            start=time.perf_counter(); at=datetime.now(timezone.utc).isoformat()
            try:
                r=await client.get(req.target, headers={'Cache-Control':'no-cache'})
                results.append({'sequence':i+1,'at':at,'elapsed_ms':round((time.perf_counter()-start)*1000,2),'status':r.status_code,'ok':r.status_code < 500})
            except Exception as e:
                results.append({'sequence':i+1,'at':at,'elapsed_ms':round((time.perf_counter()-start)*1000,2),'ok':False,'error':str(e)})
    good=[x['elapsed_ms'] for x in results if x.get('ok')]
    return {'target':req.target,'results':results,'successful_probes':len(good),'average_ms':round(sum(good)/len(good),2) if good else None,
            'min_ms':min(good) if good else None,'max_ms':max(good) if good else None,'server_time':datetime.now(timezone.utc).isoformat()}
