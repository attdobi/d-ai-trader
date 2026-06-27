#!/usr/bin/env python3
"""One-off A/B: run the summarizer on the SAME screenshots through two models
to quantify image-token inflation + real cost. Makes 2 real API calls.

Usage: ./dai/bin/python ab_summarizer_cost.py
"""
import sys
from sqlalchemy import text
from openai import OpenAI

from config import engine, PromptManager, compute_api_cost

IMAGES = [
    "screenshots/20260626T111531/Agent_CNBC_1.png",
    "screenshots/20260626T111531/Agent_CNBC_2.png",
]
MODELS = ["gpt-5.4-mini", "gpt-5.5"]

# Representative summarizer prompt from the active version.
try:
    from prompt_manager import get_active_prompt
    ap = get_active_prompt("SummarizerAgent") or {}
except Exception:
    ap = {}
system_prompt = ap.get("system_prompt") or "Extract actionable trading signals from these financial-news screenshots."
user_tmpl = ap.get("user_prompt_template") or "Summarize into 3 ticker-driven headlines and a ~200-word insight."
prompt = user_tmpl.replace("{content}", "(see screenshots)").replace("{feedback_context}", "")

client = OpenAI()
pm = PromptManager(client=client, session=None, run_id=None)

with engine.begin() as conn:
    conn.execute(text("DELETE FROM api_usage WHERE run_id LIKE 'ABTEST%'"))

for model in MODELS:
    pm.run_id = f"ABTEST::{model}"
    print(f"\n▶ {model} (medium reasoning, same 2 CNBC images)…")
    try:
        resp = pm.ask_openai(prompt, system_prompt, agent_name="SummarizerAgent",
                             image_paths=IMAGES, model_override=model)
        ok = not (isinstance(resp, dict) and resp.get("error"))
        print(f"   {'ok' if ok else 'error: ' + str(resp)[:120]}")
    except Exception as exc:
        print(f"   call failed: {exc}")

print("\n=== RESULT (same images, medium reasoning) ===")
rows_by_model = {}
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT model, prompt_tokens, completion_tokens, reasoning_tokens
        FROM api_usage WHERE run_id LIKE 'ABTEST%' ORDER BY id
    """)).fetchall()
for r in rows:
    rows_by_model[r.model] = r
    cost = compute_api_cost(r.model, int(r.prompt_tokens), int(r.completion_tokens))
    print(f"  {r.model:14}  prompt(img+text)={r.prompt_tokens:>6}  output={r.completion_tokens:>6} "
          f"(reasoning {r.reasoning_tokens})  cost=${cost:.4f}")

if all(m in rows_by_model for m in MODELS):
    mini, full = rows_by_model["gpt-5.4-mini"], rows_by_model["gpt-5.5"]
    cm = compute_api_cost("gpt-5.4-mini", int(mini.prompt_tokens), int(mini.completion_tokens))
    cf = compute_api_cost("gpt-5.5", int(full.prompt_tokens), int(full.completion_tokens))
    print("\n  image+prompt tokens — mini vs 5.5: "
          f"{mini.prompt_tokens} vs {full.prompt_tokens} "
          f"({mini.prompt_tokens / max(full.prompt_tokens,1):.1f}× ratio)")
    if cm:
        print(f"  cost per call — mini ${cm:.4f} vs 5.5 ${cf:.4f}  → 5.5 is {cf/cm:.1f}× mini")

with engine.begin() as conn:
    conn.execute(text("DELETE FROM api_usage WHERE run_id LIKE 'ABTEST%'"))
print("\n(cleaned up test rows)")
