"""Sanitization models for tracking injection detection and trace cleaning."""

from typing import Literal

from pydantic import BaseModel, Field


class InjectionAttempt(BaseModel):
    """A detected prompt injection attempt in agent output."""

    pattern_matched: str
    location: str
    raw_content: str = Field(max_length=200)
    severity: Literal["high", "medium", "low"]


class SanitizationReport(BaseModel):
    """Logged per trace evaluation. Tracks what was stripped and why."""

    trace_id: str
    items_stripped: int = 0
    injection_attempts: list[InjectionAttempt] = Field(default_factory=list)
    patterns_found: dict[str, int] = Field(default_factory=dict)
