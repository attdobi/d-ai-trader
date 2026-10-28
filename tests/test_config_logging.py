"""Bootstrap diagnostics must not reveal credential values or database URLs."""
from __future__ import annotations

import types

import pytest

from tests.test_config_model_overrides import _import_config


@pytest.mark.parametrize("debug_value", ("full", "1"))
def test_key_debug_reports_presence_only(monkeypatch, capsys, debug_value):
    key = "sk-unit-test-secret-value"
    uri = "postgresql://operator:unit-test-db-password@localhost/private-db"
    _import_config(monkeypatch, env={"OPENAI_API_KEY": key, "PRINT_OPENAI_KEY": debug_value, "DATABASE_URI": uri})
    output = capsys.readouterr().out
    assert "OPENAI_API_KEY present=True" in output
    assert key not in output and "sk-uni" not in output and "value" not in output
    assert uri not in output and "unit-test-db-password" not in output and "private-db" not in output


def test_database_failure_omits_url_and_driver_exception_text(monkeypatch, capsys):
    cfg = _import_config(monkeypatch)
    capsys.readouterr()
    primary_uri = "postgresql://operator:unit-test-db-password@localhost/private-db"
    fallback_uri = "sqlite:///unit-test-sensitive-path.db"
    fallback = types.SimpleNamespace()

    def create_engine(uri, **kwargs):
        if uri == primary_uri:
            raise cfg.OperationalError("connection failed for " + primary_uri)
        assert uri == fallback_uri
        return fallback

    monkeypatch.setattr(cfg, "DEFAULT_DB_URI", primary_uri)
    monkeypatch.setattr(cfg, "FALLBACK_DB_URI", fallback_uri)
    monkeypatch.setattr(cfg, "create_engine", create_engine)
    assert cfg._create_engine() is fallback
    output = capsys.readouterr().out
    assert "OperationalError" in output and "sqlite" in output
    for secret in (primary_uri, fallback_uri, "unit-test-db-password", "private-db", "unit-test-sensitive-path"):
        assert secret not in output
