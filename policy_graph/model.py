"""Shared vocabulary and data shapes for the policy graph (stdlib only)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Optional

# ----------------------------------------------------------------------------- agents
AGENT_PREFIX = {"DeciderAgent": "DA", "SummarizerAgent": "SA", "FeedbackAgent": "FA"}
AGENT_DIR = {"DeciderAgent": "decider", "SummarizerAgent": "summarizer", "FeedbackAgent": "feedback"}
AGENT_LABEL = {"DeciderAgent": "Decider", "SummarizerAgent": "Summarizer", "FeedbackAgent": "Feedback"}
PREFIX_AGENT = {v: k for k, v in AGENT_PREFIX.items()}

FIELDS = ("system_prompt", "user_prompt_template", "strategy_directives", "soul", "memory")
TEMPLATE_FIELDS = ("system_prompt", "user_prompt_template")
COMPILED_FIELDS = ("strategy_directives", "soul", "memory")
FIELD_SEGMENT = {"strategy_directives": "directives", "soul": "soul", "memory": "memory"}
SEGMENT_FIELD = {v: k for k, v in FIELD_SEGMENT.items()}
FIELD_TITLE = {
    "system_prompt": "System prompt (template)",
    "user_prompt_template": "User prompt template",
    "strategy_directives": "Strategy directives",
    "soul": "Soul",
    "memory": "Memory",
}
TEMPLATE_NODE_ID = {"system_prompt": "template.system", "user_prompt_template": "template.user"}

# ----------------------------------------------------------------------------- enums
NODE_TYPES = ("root", "template", "field", "section", "rule", "lesson", "entry", "reminder",
              "identity", "note", "code", "data", "ltm", "ticker", "concept")
POLARITIES = ("gate", "action", "caution", "principle", "evidence", "structure", "mixed")
POLARITY_SOURCES = ("override", "heuristic", "authored")
OWNERS = ("db", "default-file", "code", "decider_memory", "runtime", "generated")
STATUSES = ("active", "inherited", "inert", "read-only", "generated", "inactive")
COMPILED = ("stored", "effective-only", "never")
EDGE_TYPES = (
    # RUSH seven — accepted by the parser/validator, not emitted in Phase 1
    "subtype_of", "exception_to", "boundary_with", "confused_with", "clarifies", "example_of", "negative_example_of",
    # trading additions
    "includes", "related_to", "cites", "overlaps", "constrains", "enforced_by",
)

ID_RE = re.compile(r"^(DA|SA|FA)(\.[a-z0-9_]+)+$")
VERSION_DIR_RE = re.compile(r"^v(\d+)$")

# ----------------------------------------------------------------------------- colours (mirrored in JS)
COLORS = {
    "root": "#42c9ff",
    "structure": "#7f8ca6",
    "gate": "#ff5f73",
    "action": "#29d697",
    "caution": "#fadb5f",
    "principle": "#b28dff",
    "evidence": "#4dd0e1",
    "mixed": "#9aa7c7",
    "code_ring": "#ff9f43",
}

# ----------------------------------------------------------------------------- heading aliases
# (prefix of the normalised heading → slug). Order matters: first prefix match wins.
HEADING_ALIASES = [
    ("ground truth", "ground_truth"),
    ("current strategy", "strategy"),
    ("latest feedback reminder", "reminder"),
    ("mission", "mission"),
    ("shared principles", "principles"),
    ("core philosophy", "core_philosophy"),
    ("decision style", "decision_style"),
    ("risk management", "risk_management"),
    ("lessons learned", "lessons"),
    ("patterns to watch", "patterns"),
    ("mistakes to avoid", "mistakes"),
    ("log", "log"),
    ("evidence discipline", "evidence_discipline"),
    ("per-agent edge", "per_agent_edge"),
    ("current evolution focus", "evolution_focus"),
    ("operating identity", "operating_identity"),
    ("review style", "review_style"),
    ("extraction style", "extraction_style"),
    ("catalyst-provenance standard", "catalyst_provenance"),
    ("what the decider actually uses", "decider_uses"),
    ("source quality notes", "source_quality"),
    ("extraction patterns", "extraction_patterns"),
    ("media-manipulation watch", "media_manipulation"),
    ("anti-hallucination rules", "anti_hallucination"),
    ("primary mission", "primary_mission"),
    ("account mode", "account_mode"),
    ("holding window", "holding_window"),
    ("daily pacing", "daily_pacing"),
    ("hard sell rule", "hard_sell_rule"),
    ("crowd-fade reasoning", "crowd_fade"),
    ("cash account playbook", "cash_playbook"),
    ("loser management", "loser_management"),
    ("hold duration awareness", "hold_duration"),
    ("reason content", "reason_content"),
    ("core decider rules", "core_rules"),
    ("holding triage", "holding_triage"),
    ("profit harvesting", "profit_harvesting"),
    ("loss containment", "loss_containment"),
    ("buy selection", "buy_selection"),
    ("cash discipline", "cash_discipline"),
    ("feedback calibration", "feedback_calibration"),
    ("anti-patterns in my own feedback", "anti_patterns"),
    ("cross-agent observations", "cross_agent"),
    ("current battle focus", "battle_focus"),
    ("failure pattern to hunt", "failure_pattern"),
    ("style", "style"),
]

# wiki-link targets that do not resolve to a node id
LINK_ALIASES = {
    "feedback_agent": "FA.root",
    "feedback-agent": "FA.root",
    "decider": "DA.root",
    "decider_agent": "DA.root",
    "summarizer": "SA.root",
    "summarizer_agent": "SA.root",
    "front-run-not-chase": "DA.soul.core_philosophy",
}

STOPWORDS = {"the", "a", "an", "and", "of", "for", "to", "in", "on", "with"}

# ----------------------------------------------------------------------------- polarity
POLARITY_OVERRIDES = {
    "ground_truth": "gate", "strategy": "mixed", "regime_gate": "gate", "extension_cap": "gate",
    "priced_kill": "gate", "re_entry_quarantine": "gate", "reentry_quarantine": "gate", "correlation": "gate",
    "harvest": "action", "reminder": "caution", "mission": "principle", "principles": "principle",
    "identity": "principle", "core_philosophy": "principle", "decision_style": "principle",
    "risk_management": "gate", "lessons": "evidence", "patterns": "evidence", "mistakes": "evidence",
    "log": "structure", "root": "structure", "template": "structure", "system": "structure", "user": "structure",
    "code.deploy_policy": "action", "code.crowd_fade": "caution", "code.data_availability": "caution",
    "code.confirmation_policy": "gate", "code.recency_provenance": "gate", "code.cash_disclosure": "structure",
    "code.guideline_citations": "structure",
    "code.justification_detail": "structure", "code.considered_setups": "structure", "code.cash_playbook": "caution",
    "code.index_regime": "gate", "code.watchlist_header": "action", "code.quarantine_line": "gate",
    "code.lessons_header": "structure", "code.recent_activity_header": "structure", "code.json_fallback": "structure",
    "code.feedback_suffix": "structure", "code.system_base": "structure", "code.base_instructions": "structure",
    "code.json_format": "structure", "ltm": "evidence", "runtime": "structure",
    # field group nodes (the preamble slice) are structural containers
    "directives": "structure", "soul": "structure", "memory": "structure", "code": "structure",
}
POLARITY_KEYWORDS = (
    ("gate", re.compile(r"\b(never|must not|reject|only valid|do not|no buy|quarantine|cap\b|binding|invalid)", re.I)),
    ("action", re.compile(r"\b(harvest|deploy|rotate|sell|take profit|buy the)\b", re.I)),
    ("caution", re.compile(r"\b(aware|lens|prefer|consider|treat .{1,40} as|audit)\b", re.I)),
)
FIELD_DEFAULT_POLARITY = {"soul": "principle", "memory": "evidence"}

LOCKED_LAST_SEGMENTS = {"mission", "principles", "ground_truth"}


# ----------------------------------------------------------------------------- slugs
def slugify(text: str, maxlen: int = 40) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[—–]", "-", s)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if len(s) > maxlen:
        cut = s[:maxlen].rsplit("_", 1)[0]
        s = cut or s[:maxlen]
    return s or "node"


def normalize_heading(text: str) -> str:
    """Heading text → lowercase key used for alias matching (strip emoji/symbols, trailing
    parenthetical, and anything after the first ' — ', ' - ' or ':')."""
    t = (text or "").strip()
    t = re.sub(r"^[^\w]+", "", t)
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    for sep in (" — ", " – ", " - ", ":"):
        if sep in t:
            t = t.split(sep, 1)[0]
    # a parenthetical that sat before the cut point ("AUDIT ORDER (2026-09-02):") is stripped too
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def slug_for_heading(text: str) -> str:
    t = normalize_heading(text)
    for prefix, slug in HEADING_ALIASES:
        if t.startswith(prefix):
            return slug
    words = [w for w in re.split(r"[^a-z0-9]+", t) if w and w not in STOPWORDS][:4]
    return slugify("_".join(words)) if words else "section"


# ----------------------------------------------------------------------------- data shapes
@dataclass(frozen=True)
class Slice:
    start: int
    end: int
    level: int
    kind: str
    heading: str = ""


@dataclass
class Node:
    id: str
    agent: str
    title: str
    node_type: str
    parent: Optional[str]
    field: Optional[str]
    body: str
    sep_before: str = ""
    sep_after: str = ""
    order: int = 0
    polarity: str = "mixed"
    polarity_source: str = "heuristic"
    owner: str = "db"
    status: str = "active"
    compiled: str = "stored"
    locked: bool = False
    provenance: str = ""
    tags: list = dc_field(default_factory=list)
    tickers: list = dc_field(default_factory=list)
    links: list = dc_field(default_factory=list)      # raw [[x]] targets
    extra: dict = dc_field(default_factory=dict)      # owner-specific frontmatter (inherited_*, code_*, ltm row fields)
    edges: list = dc_field(default_factory=list)      # authored frontmatter edges: [{type, to, via?, confidence?}]

    @property
    def depth(self) -> int:
        return self.id.count(".")

    @property
    def text(self) -> str:
        return self.sep_before + self.body + self.sep_after


@dataclass
class Edge:
    source: str
    target: str
    edge_type: str
    confidence: Optional[float] = 1.0
    provenance: str = "derived"
    version: str = ""
    via: Optional[str] = None

    def key(self):
        return (self.source, self.target, self.edge_type)

    def to_record(self) -> dict:
        rec = {
            "source_node_id": self.source,
            "target_node_id": self.target,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "version": self.version,
        }
        if self.via is not None:
            rec["via"] = self.via
        return rec


@dataclass
class GraphBuild:
    nodes: list                      # list[Node] in document order (db/inherited/generated/code/ltm)
    edges: list                      # list[Edge]
    compile_order: dict              # field -> [node ids] (db nodes only)
    fields_meta: dict                # field -> {stored_null, stored_empty, inherited, ...}
    root_id: str = ""


@dataclass
class Version:
    path: object                     # pathlib.Path of the version dir
    manifest: dict
    nodes: dict                      # id -> Node (db + inherited + generated + linked code/ltm)
    edges: list                      # list[Edge]

    @property
    def version(self) -> int:
        return int(self.manifest.get("version", 0))

    @property
    def agent_type(self) -> str:
        return self.manifest.get("agent_type", "")


@dataclass
class InheritedText:
    text: str
    source_path: str
    git_sha: Optional[str]
    resolution: str                  # 'git-blob-at-created_at' | 'worktree' | 'live-mirror'


@dataclass
class RowMeta:
    prompt_version_id: int
    created_at: object               # datetime
    created_by: str
    description: str = ""
    is_active: bool = False


def actor_kind(created_by: str) -> str:
    cb = (created_by or "").strip()
    if cb == "system":
        return "weekly"
    if cb == "prompt_lab":
        return "human"
    if cb == "claude_code":
        return "claude_code"
    if cb in ("init_database", "auto_init", "prompt_reset"):
        return "seed"
    if cb == "policy_graph":
        return "rl_loop"
    return cb or "unknown"


def version_stamp(agent_type: str, config_hash: str, version: int) -> str:
    return f"{agent_type}.{config_hash}.v{version}"
