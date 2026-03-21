"""Tests for GPT-5.4 model configuration, reasoning params, and token caps."""

from __future__ import annotations

import importlib
import sys
import types


def _install_config_import_stubs(monkeypatch, *, dotenv_data=None):
    """Stub heavy modules so importing `config` stays local and deterministic."""

    sqlalchemy_stub = types.ModuleType("sqlalchemy")

    class _DummyResult:
        def scalar(self):
            return 1

    class _DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return _DummyResult()

    class _DummyEngine:
        def connect(self):
            return _DummyConn()

        def begin(self):
            return _DummyConn()

    sqlalchemy_stub.create_engine = lambda *_args, **_kwargs: _DummyEngine()
    sqlalchemy_stub.Column = lambda *_args, **_kwargs: None
    sqlalchemy_stub.Integer = object
    sqlalchemy_stub.String = object
    sqlalchemy_stub.DateTime = object
    sqlalchemy_stub.Text = object
    sqlalchemy_stub.text = lambda sql: sql
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_stub)

    sqlalchemy_exc_stub = types.ModuleType("sqlalchemy.exc")

    class _OperationalError(Exception):
        pass

    sqlalchemy_exc_stub.OperationalError = _OperationalError
    monkeypatch.setitem(sys.modules, "sqlalchemy.exc", sqlalchemy_exc_stub)

    sqlalchemy_ext_stub = types.ModuleType("sqlalchemy.ext")
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext", sqlalchemy_ext_stub)

    sqlalchemy_decl_stub = types.ModuleType("sqlalchemy.ext.declarative")

    class _DummyMeta:
        def create_all(self, *_args, **_kwargs):
            return None

    def _declarative_base():
        class _Base:
            metadata = _DummyMeta()

        return _Base

    sqlalchemy_decl_stub.declarative_base = _declarative_base
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext.declarative", sqlalchemy_decl_stub)

    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")

    class _SessionFactory:
        def __call__(self):
            return object()

    class _ScopedSession:
        def __init__(self, factory):
            self._factory = factory

        def __call__(self):
            return self._factory()

        def remove(self):
            return None

    sqlalchemy_orm_stub.sessionmaker = lambda *_args, **_kwargs: _SessionFactory()
    sqlalchemy_orm_stub.scoped_session = lambda factory: _ScopedSession(factory)
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm", sqlalchemy_orm_stub)

    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *_args, **_kwargs: (dotenv_data or {})
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_stub)

    openai_stub = types.ModuleType("openai")
    openai_stub.api_key = None
    monkeypatch.setitem(sys.modules, "openai", openai_stub)


def _import_config(monkeypatch, *, env=None, dotenv_data=None):
    """Import a fresh config module instance with controlled env/stubs."""
    for key in (
        "OPENAI_API_KEY",
        "DAI_GPT_MODEL",
        "DAI_MODEL_SUMMARIZER",
        "DAI_MODEL_DECIDER",
        "DAI_MODEL_FEEDBACK",
        "DAI_DECIDER_REASONING_LEVEL",
        "DAI_FEEDBACK_REASONING_LEVEL",
        "DAI_SUMMARIZER_REASONING_LEVEL",
        "DAI_DISABLE_REASONING_PARAM",
        "DATABASE_URI",
        "DATABASE_URL",
        "FALLBACK_DATABASE_URI",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    for key, value in (env or {}).items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    _install_config_import_stubs(monkeypatch, dotenv_data=dotenv_data)
    sys.modules.pop("config", None)
    return importlib.import_module("config")


# --- GPT-5.4 as default model ---

def test_default_model_is_gpt54(monkeypatch):
    cfg = _import_config(monkeypatch)
    assert cfg.GPT_MODEL == "gpt-5.4"


def test_all_agents_default_to_gpt54(monkeypatch):
    cfg = _import_config(monkeypatch)
    for agent in ("DeciderAgent", "FeedbackAgent", "SummarizerAgent"):
        assert cfg.get_agent_model(agent) == "gpt-5.4", f"{agent} should default to gpt-5.4"


# --- Reasoning levels ---

def test_decider_default_reasoning_is_high(monkeypatch):
    cfg = _import_config(monkeypatch)
    assert cfg.get_agent_reasoning_level("DeciderAgent") == "high"


def test_feedback_default_reasoning_is_high(monkeypatch):
    cfg = _import_config(monkeypatch)
    assert cfg.get_agent_reasoning_level("FeedbackAgent") == "high"


def test_summarizer_default_reasoning_is_medium(monkeypatch):
    cfg = _import_config(monkeypatch)
    assert cfg.get_agent_reasoning_level("SummarizerAgent") == "medium"


def test_reasoning_level_env_override(monkeypatch):
    cfg = _import_config(monkeypatch, env={"DAI_DECIDER_REASONING_LEVEL": "medium"})
    assert cfg.get_agent_reasoning_level("DeciderAgent") == "medium"


# --- Token caps ---

def test_high_reasoning_token_limit_is_12000(monkeypatch):
    cfg = _import_config(monkeypatch)
    assert cfg.REASONING_LEVEL_TOKEN_LIMITS["high"] == 12000


def test_decider_token_cap_for_gpt54(monkeypatch):
    cfg = _import_config(monkeypatch)
    cap = cfg.get_reasoning_token_cap("DeciderAgent", "gpt-5.4", 8000)
    assert cap == 12000, "DeciderAgent with high reasoning on gpt-5.4 should get 12000 tokens"


def test_feedback_token_cap_for_gpt54(monkeypatch):
    cfg = _import_config(monkeypatch)
    cap = cfg.get_reasoning_token_cap("FeedbackAgent", "gpt-5.4", 4000)
    assert cap == 12000, "FeedbackAgent with high reasoning on gpt-5.4 should get 12000 tokens"


def test_summarizer_token_cap_for_gpt54(monkeypatch):
    cfg = _import_config(monkeypatch)
    cap = cfg.get_reasoning_token_cap("SummarizerAgent", "gpt-5.4", 6000)
    assert cap == 6000, "SummarizerAgent with medium reasoning should get 6000 tokens"


def test_non_gpt5_model_returns_default_cap(monkeypatch):
    cfg = _import_config(monkeypatch)
    cap = cfg.get_reasoning_token_cap("DeciderAgent", "gpt-4o", 8000)
    assert cap == 8000, "Non-GPT-5 model should return the provided default cap"


# --- Reasoning params ---

def test_reasoning_params_include_effort_for_gpt54(monkeypatch):
    cfg = _import_config(monkeypatch)
    params = cfg.get_reasoning_params("DeciderAgent", "gpt-5.4")
    assert "reasoning_effort" in params
    assert params["reasoning_effort"] == "high"


def test_reasoning_params_empty_for_non_gpt5(monkeypatch):
    cfg = _import_config(monkeypatch)
    params = cfg.get_reasoning_params("DeciderAgent", "gpt-4o")
    assert params == {}


def test_reasoning_params_disabled_via_env(monkeypatch):
    cfg = _import_config(monkeypatch, env={"DAI_DISABLE_REASONING_PARAM": "1"})
    params = cfg.get_reasoning_params("DeciderAgent", "gpt-5.4")
    assert params == {}


# --- Temperature params ---

def test_gpt54_no_custom_temperature(monkeypatch):
    cfg = _import_config(monkeypatch)
    params = cfg.get_model_temperature_params("gpt-5.4", 0.7)
    assert params == {}, "GPT-5.4 should not send temperature parameter"


def test_gpt4o_gets_custom_temperature(monkeypatch):
    cfg = _import_config(monkeypatch)
    params = cfg.get_model_temperature_params("gpt-4o", 0.7)
    assert params == {"temperature": 0.7}
