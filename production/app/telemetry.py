import json, os, asyncio
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Event, uid
from .config import settings

_jsonl_lock = asyncio.Lock()

async def record_event(db: AsyncSession, trace_id: str, event_type: str, payload=None,
                       request_id=None, participant_id=None, client_monotonic_ms=None):
    now = datetime.now(timezone.utc)
    event = Event(
        id=uid("evt"), trace_id=trace_id, request_id=request_id,
        participant_id=participant_id, event_type=event_type,
        occurred_at=now, client_monotonic_ms=client_monotonic_ms,
        payload=payload or {}
    )
    db.add(event)
    await db.flush()
    record = {
        "event_id": event.id, "trace_id": trace_id, "request_id": request_id,
        "participant_id": participant_id, "event_type": event_type,
        "occurred_at": now.isoformat(), "client_monotonic_ms": client_monotonic_ms,
        "payload": payload or {}
    }
    # JSONL is an append-only secondary audit stream; PostgreSQL remains authoritative.
    async with _jsonl_lock:
        path = Path(settings.jsonl_dir)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        target = path / f"{now:%Y-%m-%d}.jsonl"
        fd = os.open(target, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event
