"""Frozen Decider screenshots survive provider retries without becoming log text."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_config_model_overrides import _import_config

ROOT = Path(__file__).resolve().parents[1]


class Bundle:
    def __init__(self, count=12):
        self.parts = []
        for n in range(count):
            self.parts.extend([
                {"type": "text", "text": f"Image I{n+1:02}: source {n//2}; view {n%2+1}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,aW1hZ2U{n}", "detail": "high"}},
            ])
        self.reads = 0

    def chat_parts(self):
        self.reads += 1
        return deepcopy(self.parts)

    def public_manifest(self):
        return {"schema_version": 1, "image_count": len(self.parts)//2,
                "snapshot_hash": "frozen-test", "images": [{"image_id": "I01", "sha256": "hash-only"}]}


def manager(monkeypatch, outcomes, model="gpt-6.1-sol", mutation=None):
    cfg = _import_config(monkeypatch, env={"DAI_GPT_MODEL": model, "DAI_MODEL_DECIDER": None,
        "DAI_DECIDER_REASONING_LEVEL": "high", "DAI_REASONING_LEVEL": None,
        "DAI_DISABLE_REASONING_PARAM": None})
    monkeypatch.setattr(cfg.time, "sleep", lambda _: None)
    calls = []
    class Completions:
        def create(self, **params):
            calls.append(deepcopy(params))
            if mutation:
                mutation(params, len(calls))
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=result))], usage=None)
    pm = cfg.PromptManager(SimpleNamespace(chat=SimpleNamespace(completions=Completions())), session=None)
    return pm, calls


def images(call):
    return [part for part in call["messages"][1]["content"] if part["type"] == "image_url"]


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-4.1", "gpt-4-turbo"])
def test_all_twelve_images_use_real_vision_parts_and_plain_prompt_logs(monkeypatch, model):
    pm, calls = manager(monkeypatch, ['{"decisions": [], "visual_context": []}'], model=model)
    bundle = Bundle()
    assert pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=bundle) == {"decisions": [], "visual_context": []}
    assert len(images(calls[0])) == 12
    assert all(part["image_url"]["detail"] == "high" for part in images(calls[0]))
    assert calls[0]["messages"][1]["content"][0] == {"type": "text", "text": "TEXT"}
    last = pm.last_reply()
    assert last["user_prompt"] == "TEXT" and last["image_manifest"]["image_count"] == 12
    assert "data:image" not in json.dumps(last) and "base64" not in json.dumps(last)
    assert bundle.reads == 1


def test_retries_keep_snapshot_when_bundle_and_client_mutate(monkeypatch):
    bundle = Bundle()
    original = deepcopy(bundle.parts)
    def mutate(params, number):
        bundle.parts[1]["image_url"]["url"] = "data:image/png;base64,CHANGED"
        params["messages"][1]["content"][2]["image_url"]["url"] = "data:image/png;base64,MUTATED"
    pm, calls = manager(monkeypatch, ["not valid json", RuntimeError("timeout"), '{"decisions": [1]}'], mutation=mutate)
    assert pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=bundle) == {"decisions": [1]}
    assert len(calls) == 3 and bundle.reads == 1
    expected = [part for part in original if part["type"] == "image_url"]
    assert all(images(call) == expected for call in calls)


def test_model_fallback_preserves_same_frozen_images(monkeypatch):
    bundle = Bundle()
    pm, calls = manager(monkeypatch, ["[]", '[{"action":"hold"}]'])
    assert pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=bundle) == [{"action": "hold"}]
    assert [call["model"] for call in calls] == ["gpt-6.1-sol", "gpt-4.1"]
    assert images(calls[0]) == images(calls[1]) and bundle.reads == 1
    assert pm.last_reply()["model"] == "gpt-4.1" and pm.last_reply()["image_manifest"]["image_count"] == 12


def test_provider_error_cannot_echo_encoded_pixels_into_logs_or_result(monkeypatch, capsys):
    raw = "data:image/png;base64,DO_NOT_LOG_PIXELS"
    pm, _ = manager(monkeypatch, [RuntimeError(raw)])
    result = pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=Bundle(), max_retries=1)
    assert raw not in json.dumps(result) and raw not in capsys.readouterr().out
    assert "RuntimeError" in result["insights"] and pm.last_reply() is None


def test_remote_or_mixed_inputs_are_rejected_before_provider_call(monkeypatch):
    pm, calls = manager(monkeypatch, [])
    bundle = Bundle(1)
    bundle.parts[1]["image_url"]["url"] = "https://untrusted.invalid/image.png"
    with pytest.raises(ValueError, match="attachment"):
        pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=bundle)
    with pytest.raises(ValueError, match="either"):
        pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=Bundle(), image_paths=["other.png"])
    assert calls == []


def test_decider_wires_one_selected_bundle_to_both_consumers_but_not_citation_repair():
    tree = ast.parse((ROOT / "decider_agent.py").read_text())
    ask = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "ask_decision_agent")
    find = lambda name: [node for node in ast.walk(ask) if isinstance(node, ast.Call) and
                        (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) == name]
    frozen = find("freeze_summary_images")
    assert len(frozen) == 1 and getattr(frozen[0].args[0], "id", None) == "summaries"
    assert {kw.arg for kw in frozen[0].keywords} == {"screenshot_root", "config_hash", "decision_run_id"}
    router = find("_policy_router_cycle")[0]
    main = find("ask_openai")[0]
    assert next(kw.value.id for kw in router.keywords if kw.arg == "image_bundle") == "_router_images"
    assert next(kw.value.id for kw in main.keywords if kw.arg == "image_bundle") == "_decider_images"
    repair = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_repair_missing_citations")
    for call in ast.walk(repair):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "ask_openai":
            assert not {"image_bundle", "image_paths"} & {kw.arg for kw in call.keywords}


def test_runtime_visual_labels_are_nonbinding_and_mark_missing_images_unknown():
    tree = ast.parse((ROOT / "decider_agent.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_visual_image_context")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "visual-context", "exec"), ns)
    text = ns[fn.name](None, error="ReadError")
    assert "No usable screenshot" in text and "do not guess identity" in text
    assert "actual feelings" in text and "unknown, not bearish" in text
    assert "cannot override ownership" in text and "data:image" not in text


def test_same_selected_cycle_pixels_reach_router_and_decider_after_disk_change(monkeypatch, tmp_path):
    from PIL import Image
    from cycle_images import freeze_summary_images
    from policy_router.decisions import build_request
    from policy_router.features import CycleContext
    from policy_router.nodes import RouterNode

    screenshot_root = tmp_path / "screenshots"
    directory = screenshot_root / "cfg" / "20261029T083047"
    directory.mkdir(parents=True)
    summaries = []
    for source in range(6):
        name = f"Agent_Source{source}"
        paths = []
        for view in (1, 2):
            path = directory / f"{name}_{view}.png"
            Image.new("RGB", (32, 32), (source * 20, view * 20, 0)).save(path)
            paths.append(str(path))
        summaries.append({"id": source + 1, "agent": name, "run_id": directory.name,
                          "config_hash": "cfg", "data": {"agent": name, "run_id": directory.name,
                                                          "screenshot_paths": paths}})
    bundle = freeze_summary_images(summaries, screenshot_root=screenshot_root, config_hash="cfg",
                                   decision_run_id="20261029T083050")
    assert len(bundle.attachments) == 12
    # Replacing a source file after collection must affect neither API request.
    Image.new("RGB", (32, 32), "white").save(paths[-1])
    payload, *_ = build_request(CycleContext(), [RouterNode("DA.ltm.1", "ltm", "A supplied lesson", 17)],
                                image_bundle=bundle)
    router_images = [part["image_url"] for part in payload["input"][0]["content"] if part["type"] == "input_image"]
    pm, calls = manager(monkeypatch, ['{"decisions": [], "visual_context": []}'])
    pm.ask_openai("TEXT", "SYSTEM", agent_name="DeciderAgent", image_bundle=bundle)
    decider_images = [part["image_url"]["url"] for part in images(calls[0])]
    assert router_images == decider_images and len(router_images) == 12
    manifest = pm.last_reply()["image_manifest"]
    assert manifest["snapshot_hash"] == bundle.public_manifest()["snapshot_hash"]
    assert "relative_path" not in json.dumps(manifest) and "data:image" not in json.dumps(manifest)
