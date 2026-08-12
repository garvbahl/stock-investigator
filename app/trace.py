import time
from typing import Optional

from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    stage: str                       # machine key, e.g. "fetch", "agent:bull"
    label: str                       # human label, e.g. "Bull agent"
    kind: str                        # "tool" | "verify" | "decision" | "agent"
    status: str = "ok"              # "ok" | "warn" | "stop"
    detail: str = ""                # one-line human description
    facts_verified: Optional[int] = None
    unknown_count: Optional[int] = None
    tier: Optional[str] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    attempts: Optional[int] = None
    reads: list[str] = Field(default_factory=list)  # which prior steps it consumed
    ms: Optional[float] = None       # wall-clock duration


class Trace(BaseModel):
    steps: list[TraceStep] = Field(default_factory=list)

    def add(self, step: TraceStep) -> None:
        self.steps.append(step)

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd or 0.0 for s in self.steps)

    @property
    def total_tokens(self) -> int:
        return sum((s.input_tokens or 0) + (s.output_tokens or 0) for s in self.steps)


class _Timer:
    """Context manager that appends a step with its measured duration."""

    def __init__(self, trace: Trace, step: TraceStep):
        self._trace = trace
        self._step = step

    def __enter__(self) -> TraceStep:
        self._start = time.monotonic()
        return self._step

    def __exit__(self, exc_type, exc, tb) -> None:
        self._step.ms = round((time.monotonic() - self._start) * 1000, 1)
        if exc_type is not None and self._step.status == "ok":
            self._step.status = "stop"
            self._step.detail = self._step.detail or f"failed: {exc}"
        self._trace.add(self._step)


def timed(trace: Trace, **step_kwargs) -> _Timer:
    return _Timer(trace, TraceStep(**step_kwargs))