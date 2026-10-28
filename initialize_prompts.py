#!/usr/bin/env python3
"""
Script to initialize default prompts in the database
"""

from pathlib import Path


def _load_agent_file(agent_name, filename, default=""):
    """Load a .md file from agents/<agent_name>/<filename>.

    Resolution order (first that exists wins):
      1. agents/<agent_name>/<filename>             — live mirror, gitignored,
         intended for runtime-evolved content (Obsidian-friendly).
      2. agents/<agent_name>/<stem>.default.<ext>   — committed seed/template.

    The split lets the canonical evolving copy live in Postgres (source of
    truth) and be optionally mirrored to disk for the upcoming Obsidian
    graph view, while the committed default keeps fresh checkouts bootable.
    """
    base = Path(__file__).parent / "agents" / agent_name
    live = base / filename
    if live.exists():
        return live.read_text().strip()
    if "." in filename:
        stem, ext = filename.rsplit(".", 1)
        fallback = base / f"{stem}.default.{ext}"
    else:
        fallback = base / f"{filename}.default"
    if fallback.exists():
        return fallback.read_text().strip()
    return default


# Current release defaults come from the reviewed, versioned operator audit.
# Existing database versions are immutable; this affects missing/fresh baselines
# only. It does not activate the audit against an existing configuration.
import json as _json
_audited_defaults = _json.loads((Path(__file__).parent / "policy_graph" / "audited_agent_prompts.json").read_text())
DEFAULT_PROMPTS = {
    agent: {**proposal["fields"], "description": proposal["description"]}
    for agent, proposal in _audited_defaults["agents"].items()
}

# Legacy alias — keep for any code that still references the old name
DEFAULT_PROMPTS["feedback_analyzer"] = DEFAULT_PROMPTS["FeedbackAgent"]


def initialize_default_prompts():
    """Initialize default prompts for all agent types"""
    from feedback_agent import TradeOutcomeTracker

    tracker = TradeOutcomeTracker()
    
    # Default prompts for each agent type - ACTUAL TRADING PROMPTS (v0 baseline)
    default_prompts = DEFAULT_PROMPTS
    
    # Save default prompts for each agent type
    for agent_type, prompt_data in default_prompts.items():
        # Legacy alias points at the same payload; seed canonical key only.
        if agent_type == "feedback_analyzer":
            continue
        try:
            # Use correct field names based on the prompt data structure
            user_prompt_field = "user_prompt_template" if "user_prompt_template" in prompt_data else "user_prompt"
            
            version = tracker.save_prompt_version(
                agent_type=agent_type,
                user_prompt=prompt_data[user_prompt_field],
                system_prompt=prompt_data["system_prompt"],
                description=prompt_data["description"],
                created_by="system",
                strategy_directives=prompt_data.get("strategy_directives", ""),
                soul=prompt_data.get("soul", ""), memory=prompt_data.get("memory", ""),
            )
            print(f"✅ Initialized {agent_type} prompt (version {version})")
        except Exception as e:
            print(f"❌ Failed to initialize {agent_type} prompt: {e}")
    
    print("\n🎉 Default prompts initialized successfully!")
    print("You can now view and edit prompts through the dashboard.")


if __name__ == "__main__":
    initialize_default_prompts()
