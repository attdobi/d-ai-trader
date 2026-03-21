"""Tests for prompt loading from module files and profile switching."""

from __future__ import annotations

import os
import importlib
import sys
import types

import pytest


def _install_stubs(monkeypatch):
    """Stub sqlalchemy and config.engine so prompt_manager can import."""
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.text = lambda sql: sql
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy_stub)

    # Minimal config stub that provides `engine`
    config_stub = types.ModuleType("config")
    config_stub.engine = None
    monkeypatch.setitem(sys.modules, "config", config_stub)


def _import_prompt_manager(monkeypatch, *, profile=None):
    """Import a fresh prompt_manager with optional DAI_PROMPT_PROFILE."""
    _install_stubs(monkeypatch)

    monkeypatch.delenv("DAI_PROMPT_PROFILE", raising=False)
    if profile is not None:
        monkeypatch.setenv("DAI_PROMPT_PROFILE", profile)

    sys.modules.pop("prompt_manager", None)
    return importlib.import_module("prompt_manager")


# --- Profile switching ---

def test_default_profile_loads_standard_prompts(monkeypatch):
    pm = _import_prompt_manager(monkeypatch)
    system, user = pm._decider_prompts_for_profile()
    assert "machiavellian" in system.lower() or "trading agent" in system.lower()
    assert len(system) > 100, "Standard system prompt should be substantial"
    assert len(user) > 100, "Standard user prompt template should be substantial"


def test_gpt_pro_profile_loads_pro_prompts(monkeypatch):
    pm = _import_prompt_manager(monkeypatch, profile="gpt-pro")
    system, user = pm._decider_prompts_for_profile()
    # Both profiles mention trading but pro has different structure
    assert len(system) > 100
    assert len(user) > 100


def test_standard_and_pro_prompts_differ(monkeypatch):
    pm = _import_prompt_manager(monkeypatch)
    std_sys, std_user = pm._decider_prompts_for_profile()

    monkeypatch.setenv("DAI_PROMPT_PROFILE", "gpt-pro")
    pro_sys, pro_user = pm._decider_prompts_for_profile()

    assert std_sys != pro_sys, "Standard and pro system prompts should differ"
    assert std_user != pro_user, "Standard and pro user prompts should differ"


def test_unknown_profile_falls_back_to_standard(monkeypatch):
    pm = _import_prompt_manager(monkeypatch, profile="nonexistent")
    system, user = pm._decider_prompts_for_profile()
    # Should get standard prompts (fallback)
    from prompts.decider_standard_prompt import STANDARD_SYSTEM_PROMPT
    assert system == STANDARD_SYSTEM_PROMPT.strip()


# --- Decider override application ---

def test_apply_decider_overrides_replaces_prompts(monkeypatch):
    pm = _import_prompt_manager(monkeypatch)
    payload = {
        "system_prompt": "old system prompt",
        "user_prompt_template": "old user prompt",
        "version": 1,
    }
    result = pm._apply_decider_overrides("DeciderAgent", payload)
    assert result["system_prompt"] != "old system prompt"
    assert result["user_prompt_template"] != "old user prompt"
    assert result["version"] == 1  # version preserved


def test_apply_decider_overrides_ignores_non_decider(monkeypatch):
    pm = _import_prompt_manager(monkeypatch)
    payload = {
        "system_prompt": "original",
        "user_prompt_template": "original",
        "version": 1,
    }
    result = pm._apply_decider_overrides("FeedbackAgent", payload)
    assert result["system_prompt"] == "original"


def test_apply_decider_overrides_handles_none_payload(monkeypatch):
    pm = _import_prompt_manager(monkeypatch)
    result = pm._apply_decider_overrides("DeciderAgent", None)
    assert result is None


# --- Prompt module files exist and have expected exports ---

def test_standard_prompt_module_exports():
    from prompts.decider_standard_prompt import STANDARD_SYSTEM_PROMPT, STANDARD_USER_PROMPT_TEMPLATE
    assert isinstance(STANDARD_SYSTEM_PROMPT, str)
    assert isinstance(STANDARD_USER_PROMPT_TEMPLATE, str)
    assert len(STANDARD_SYSTEM_PROMPT) > 0
    assert len(STANDARD_USER_PROMPT_TEMPLATE) > 0


def test_gpt_pro_prompt_module_exports():
    from prompts.decider_gpt_pro_prompt import GPT_PRO_SYSTEM_PROMPT, GPT_PRO_USER_PROMPT_TEMPLATE
    assert isinstance(GPT_PRO_SYSTEM_PROMPT, str)
    assert isinstance(GPT_PRO_USER_PROMPT_TEMPLATE, str)
    assert len(GPT_PRO_SYSTEM_PROMPT) > 0
    assert len(GPT_PRO_USER_PROMPT_TEMPLATE) > 0
