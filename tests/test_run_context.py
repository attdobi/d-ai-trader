from __future__ import annotations

import uuid
from datetime import datetime

from shared.run_context import RunContext


def test_create_preserves_explicit_run_id_and_config_hash():
    ctx = RunContext.create(config_hash="cfg-123", run_id="summarizer_abc")
    assert ctx.run_id == "summarizer_abc"
    assert ctx.config_hash == "cfg-123"


def test_create_generates_uuid_when_run_id_missing():
    ctx = RunContext.create(config_hash="cfg-123")
    parsed = uuid.UUID(ctx.run_id, version=4)
    assert str(parsed) == ctx.run_id


def test_timestamp_is_iso8601():
    ctx = RunContext.create(config_hash="cfg-123", run_id="r1")
    parsed = datetime.fromisoformat(ctx.timestamp)
    assert parsed.tzinfo is not None
