"""Deterministic config model-override tests (no real DB/API imports)."""

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


def test_agent_model_override_alias_gpt54_resolves_to_dash_format(monkeypatch):
    config_module = _import_config(
        monkeypatch,
        env={"DAI_MODEL_DECIDER": "gpt5.4"},
    )

    assert config_module.AGENT_MODEL_OVERRIDES["decider"] == "gpt-5.4"


def test_get_agent_model_falls_back_to_default_when_override_absent(monkeypatch):
    config_module = _import_config(monkeypatch, env={"DAI_MODEL_DECIDER": None})

    assert config_module.AGENT_MODEL_OVERRIDES["decider"] is None
    assert config_module.get_agent_model("DeciderAgent") == config_module.GPT_MODEL


def test_global_model_override_from_env_applies_on_config_import(monkeypatch):
    config_module = _import_config(monkeypatch, env={"DAI_GPT_MODEL": "gpt-4o"})

    assert config_module.get_gpt_model() == "gpt-4o"
    assert config_module.get_agent_model("DeciderAgent") == "gpt-4o"


def test_global_model_override_alias_from_env_is_normalized(monkeypatch):
    config_module = _import_config(monkeypatch, env={"DAI_GPT_MODEL": "gpt5.4"})

    assert config_module.get_gpt_model() == "gpt-5.4"

