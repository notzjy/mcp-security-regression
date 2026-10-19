from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=120)
    base_url: str
    endpoint: str = "/proofread"
    version: str = Field(min_length=1, max_length=120)
    # Mapping is explicit: no executable template strings or arbitrary Python.
    text_field: str = "text"
    session_field: str = "session_id"
    user_field: str = "user_id"
    issues_field: str = "issues"
    trace_field: str = "_trace"
    auth_env: str | None = None
    timeout_seconds: float = Field(default=10, ge=0.1, le=60)
    supports_sessions: bool = True
    supports_trace: bool = True
    model_config_snapshot: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an HTTP(S) origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use auth_env for credentials; URL credentials/query are forbidden")
        if parsed.path not in {"", "/"}:
            raise ValueError("Put API path in endpoint, not base_url")
        return value.rstrip("/")

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "?" in value or "#" in value:
            raise ValueError("endpoint must be an absolute path without query/fragment")
        return value

    @field_validator("text_field", "session_field", "user_field", "issues_field", "trace_field")
    @classmethod
    def field_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
            raise ValueError("Only top-level JSON field names are supported")
        return value

    @field_validator("auth_env")
    @classmethod
    def env_name(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,100}", value):
            raise ValueError("auth_env is an environment variable name, never a secret value")
        return value


class Candidate(StrictModel):
    template_id: Literal["injection", "role_injection"]
    text: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=1000)


class Step(StrictModel):
    text: str
    session: str = "main"
    user: str = "user-b"
    forbidden_markers: list[str] = Field(default_factory=list)
    require_trace: bool = False


class Case(StrictModel):
    id: str
    title: str
    category: str
    rationale: str
    steps: list[Step]
    allowed_tools: list[str] = Field(default_factory=lambda: ["dictionary_lookup"])
    requires_sessions: bool = False


class Issue(BaseModel):
    # An output schema, independent of the model used for evaluation.
    original: str
    suggestion: str
    reason: str


class Check(StrictModel):
    rule: str
    status: Literal["pass", "fail", "review", "error"]
    detail: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class Finding(StrictModel):
    case_id: str
    explanation: str = Field(min_length=1, max_length=3000)
    evidence_steps: list[int] = Field(min_length=1, max_length=10)


class Analysis(StrictModel):
    summary: str = Field(min_length=1, max_length=6000)
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    recommendations: list[Candidate] = Field(default_factory=list, max_length=3)
