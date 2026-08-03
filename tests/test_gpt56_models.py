"""GPT-5.6 family (Sol/Terra/Luna) model-config tests.

Covers: alias resolution (sol/terra/tera/luna), reasoning suffixes on
dashed model names (-m gpt-5.6-terra-high), the new "max" effort tier
(5.6-only, clamped to xhigh on older models), pricing lookups, and the
API-param plumbing (max_completion_tokens / no temperature).
"""

from __future__ import annotations

from tests.test_config_model_overrides import _import_config

# Reasoning-related env that could leak in from the shell; every test
# clears these via the env dict (None → delenv).
_CLEAR_REASONING_ENV = {
    "DAI_REASONING_LEVEL": None,
    "DAI_SUMMARIZER_REASONING_LEVEL": None,
    "DAI_DECIDER_REASONING_LEVEL": None,
    "DAI_FEEDBACK_REASONING_LEVEL": None,
    "DAI_COMPANY_REASONING_LEVEL": None,
    "DAI_DISABLE_REASONING_PARAM": None,
    "DAI_MODEL_COMPANY": None,
}


def _cfg(monkeypatch, env=None):
    merged = dict(_CLEAR_REASONING_ENV)
    merged.update(env or {})
    return _import_config(monkeypatch, env=merged)


# --- model IDs + aliases ----------------------------------------------------

def test_gpt56_full_ids_are_valid(monkeypatch):
    cfg = _cfg(monkeypatch)
    for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        cfg.set_gpt_model(model)
        assert cfg.get_gpt_model() == model


def test_gpt56_short_aliases_resolve(monkeypatch):
    cfg = _cfg(monkeypatch)
    for alias, expected in (
        ("sol", "gpt-5.6-sol"),
        ("terra", "gpt-5.6-terra"),
        ("luna", "gpt-5.6-luna"),
        ("tera", "gpt-5.6-terra"),          # common misspelling
        ("gpt-5.6-tera", "gpt-5.6-terra"),  # misspelling with full prefix
        ("gpt-5.6", "gpt-5.6-sol"),         # bare 5.6 → Sol (OpenAI's alias)
        ("gpt5.6", "gpt-5.6-sol"),
    ):
        cfg.set_gpt_model(alias)
        assert cfg.get_gpt_model() == expected, f"alias {alias!r}"


def test_gpt56_agent_override_accepts_alias(monkeypatch):
    cfg = _cfg(monkeypatch, env={"DAI_MODEL_SUMMARIZER": "luna"})
    assert cfg.AGENT_MODEL_OVERRIDES["summarizer"] == "gpt-5.6-luna"
    assert cfg.get_agent_model("SummarizerAgent") == "gpt-5.6-luna"


def test_gpt56_feedback_override_resolves(monkeypatch):
    # Regression: feedback_agent used to hardcode GPT_MODEL and silently
    # ignore DAI_MODEL_FEEDBACK; the config side must resolve the alias.
    cfg = _cfg(monkeypatch, env={"DAI_MODEL_FEEDBACK": "sol"})
    assert cfg.AGENT_MODEL_OVERRIDES["feedback"] == "gpt-5.6-sol"
    assert cfg.get_agent_model("FeedbackAgent") == "gpt-5.6-sol"


def test_gpt56_global_env_model(monkeypatch):
    cfg = _cfg(monkeypatch, env={"DAI_GPT_MODEL": "gpt-5.6-terra"})
    assert cfg.get_gpt_model() == "gpt-5.6-terra"
    assert cfg.get_agent_model("DeciderAgent") == "gpt-5.6-terra"


# --- reasoning suffix parsing ----------------------------------------------

def test_gpt56_reasoning_suffix_extracted(monkeypatch):
    cfg = _cfg(monkeypatch)
    cfg.set_gpt_model("gpt-5.6-terra-high")
    assert cfg.get_gpt_model() == "gpt-5.6-terra"
    assert cfg.GLOBAL_REASONING_LEVEL == "high"


def test_gpt56_alias_plus_suffix(monkeypatch):
    cfg = _cfg(monkeypatch)
    cfg.set_gpt_model("sol-max")
    assert cfg.get_gpt_model() == "gpt-5.6-sol"
    assert cfg.GLOBAL_REASONING_LEVEL == "max"


def test_tier_names_are_not_eaten_as_reasoning_suffixes(monkeypatch):
    cfg = _cfg(monkeypatch)
    # "-sol"/"-terra"/"-luna" must never be mistaken for effort suffixes.
    for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        clean, level = cfg._extract_reasoning_suffix(model)
        assert clean == model and level is None


# --- "max" effort tier ------------------------------------------------------

def test_max_effort_passes_through_on_gpt56(monkeypatch):
    cfg = _cfg(monkeypatch, env={"DAI_DECIDER_REASONING_LEVEL": "max"})
    params = cfg.get_reasoning_params("DeciderAgent", "gpt-5.6-sol")
    assert params == {"reasoning_effort": "max"}


def test_max_effort_clamped_to_xhigh_on_older_models(monkeypatch):
    cfg = _cfg(monkeypatch, env={"DAI_DECIDER_REASONING_LEVEL": "max"})
    params = cfg.get_reasoning_params("DeciderAgent", "gpt-5.5")
    assert params == {"reasoning_effort": "xhigh"}


def test_max_effort_token_cap(monkeypatch):
    cfg = _cfg(monkeypatch, env={"DAI_DECIDER_REASONING_LEVEL": "max"})
    cap = cfg.get_reasoning_token_cap("DeciderAgent", "gpt-5.6-sol", 8000)
    assert cap == cfg.REASONING_LEVEL_TOKEN_LIMITS["max"] == 32000


# --- pricing ----------------------------------------------------------------

def test_gpt56_pricing_rates_present(monkeypatch):
    cfg = _cfg(monkeypatch)
    pricing = cfg.load_model_pricing()
    assert pricing["gpt-5.6-sol"] == {"input": 5.00, "output": 30.00}
    assert pricing["gpt-5.6-terra"] == {"input": 2.00, "output": 12.00}
    assert pricing["gpt-5.6-luna"] == {"input": 0.20, "output": 1.20}


def test_compute_api_cost_gpt56_luna(monkeypatch):
    cfg = _cfg(monkeypatch)
    # 1M in + 1M out on Luna = $0.20 + $1.20
    assert abs(cfg.compute_api_cost("gpt-5.6-luna", 1_000_000, 1_000_000) - 1.40) < 1e-9
    # alias normalizes before the pricing lookup
    assert abs(cfg.compute_api_cost("luna", 1_000_000, 1_000_000) - 1.40) < 1e-9


# --- API param plumbing -----------------------------------------------------

def test_gpt56_uses_max_completion_tokens(monkeypatch):
    cfg = _cfg(monkeypatch)
    assert cfg.get_model_token_params("gpt-5.6-sol", 9000) == {
        "max_completion_tokens": 9000
    }


def test_gpt56_no_custom_temperature(monkeypatch):
    cfg = _cfg(monkeypatch)
    assert cfg.get_model_temperature_params("gpt-5.6-luna", 0.3) == {}
