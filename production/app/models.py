import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Boolean, Integer, Float, ForeignKey, JSON, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def uid(prefix: str):
    return f"{prefix}_{uuid.uuid4().hex}"

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("usr"))
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="participant", index=True)
    participant_code: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("exp"))
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    protocol_version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    seed: Mapped[int] = mapped_column(Integer, default=20261117)
    ethics_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    ethics_approval_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    ethics_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ethics_approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("tsk"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    task_code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(240))
    prompt: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text)
    rubric: Mapped[dict] = mapped_column(JSON)
    network_profile: Mapped[dict] = mapped_column(JSON)
    model_arm: Mapped[str] = mapped_column(String(16), default="llm")
    task_order: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("experiment_id","task_code"),)

class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("asn"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, default=1)
    condition_order: Mapped[int] = mapped_column(Integer, default=1)
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("task_id","participant_id"),)

class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("trc"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    model_arm: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    client_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

class ChatRequest(Base):
    __tablename__ = "chat_requests"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("req"))
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    response_text: Mapped[str] = mapped_column(Text, default="")
    provider_model: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="running")
    finish_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    itl_mean_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tpot_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    e2e_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    response_bytes: Mapped[int] = mapped_column(Integer, default=0)
    response_chars: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_token_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("evt"))
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    participant_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    client_monotonic_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

class Questionnaire(Base):
    __tablename__ = "questionnaires"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("qnr"))
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    instrument: Mapped[str] = mapped_column(String(40), index=True)
    answers: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class RubricScore(Base):
    __tablename__ = "rubric_scores"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("rub"))
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id"), index=True)
    scorer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    criterion_scores: Mapped[dict] = mapped_column(JSON)
    total_score: Mapped[float] = mapped_column(Float)
    blinded: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelSnapshot(Base):
    __tablename__ = "model_snapshots"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("mdl"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    arm: Mapped[str] = mapped_column(String(16))
    
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="vllm")
    model_id: Mapped[str] = mapped_column(String(240), nullable=False, default="unknown")
    
    repository: Mapped[str] = mapped_column(String(240))
    revision: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSON)
    config_sha256: Mapped[str] = mapped_column(String(64))
    frozen_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("experiment_id","arm"),)
    


class ExperimentConsent(Base):
    __tablename__ = "experiment_consents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("ec"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    consent_version: Mapped[str] = mapped_column(String(40))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("experiment_id", "participant_id"),)


class MoralDilemmaSession(Base):
    __tablename__ = "moral_dilemma_sessions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: uid("mds"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), unique=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id", ondelete="CASCADE"), unique=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_version: Mapped[str] = mapped_column(String(40))
    task_source_sha256: Mapped[str] = mapped_column(String(64))
    active_stage: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    final_reflection_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
