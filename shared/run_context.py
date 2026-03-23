"""Explicit run context for orchestrator -> decider propagation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RunContext:
    """Immutable context token for a single decider cycle."""

    run_id: str
    config_hash: str
    timestamp: str

    @classmethod
    def create(cls, config_hash: str, run_id: str | None = None) -> "RunContext":
        """Build a context object with deterministic fields for downstream calls."""
        resolved_run_id = (run_id or str(uuid.uuid4())).strip() or str(uuid.uuid4())
        return cls(
            run_id=resolved_run_id,
            config_hash=(config_hash or "").strip(),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
