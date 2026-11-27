from pydantic import BaseModel, Field, ConfigDict
from typing import Any

class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=1, max_length=256)

class ParticipantCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=14, max_length=256)

class ExperimentCreate(BaseModel):
    name: str = Field(min_length=3, max_length=240)
    description: str = Field(default="", max_length=5000)
    seed: int = 20261117
    ethics_approval_ref: str = Field(default="", max_length=240)
    ethics_approved: bool = False

class ConsentIn(BaseModel):
    accepted: bool
    consent_version: str = Field(min_length=1, max_length=40)

class TaskSeedIn(BaseModel):
    tasks: list[dict[str, Any]] = Field(min_length=1, max_length=50)

class RandomizeIn(BaseModel):
    participant_ids: list[str] = Field(min_length=1, max_length=1000)
    model_arms: list[str] = ["llm", "slm"]
    network_profiles: list[dict[str, Any]] = [
        {"name":"baseline","latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0},
        {"name":"moderate","latency_ms":100,"jitter_ms":20,"loss_pct":1,"bandwidth_mbps":50},
        {"name":"high_delay","latency_ms":250,"jitter_ms":30,"loss_pct":1,"bandwidth_mbps":25},
        {"name":"constrained","latency_ms":100,"jitter_ms":50,"loss_pct":3,"bandwidth_mbps":5}
    ]

class PrepareIn(BaseModel):
    assignment_id: str
    trace_id: str

class ChatIn(BaseModel):
    assignment_id: str
    trace_id: str
    prompt: str = Field(min_length=1, max_length=20000)
    client_metadata: dict[str, Any] = Field(default_factory=dict)

class EventIn(BaseModel):
    trace_id: str
    request_id: str | None = None
    event_type: str = Field(min_length=2, max_length=100)
    client_monotonic_ms: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

class QuestionnaireIn(BaseModel):
    trace_id: str
    instrument: str
    answers: dict[str, Any]

class RubricScoreIn(BaseModel):
    trace_id: str
    criterion_scores: dict[str, float]
    blinded: bool = True


class ModelFreezeIn(BaseModel):
    models: list[dict[str, Any]] = Field(min_length=2, max_length=2)


class EthicsApprovalIn(BaseModel):
    approval_ref: str = Field(min_length=3, max_length=240)
    approved: bool
