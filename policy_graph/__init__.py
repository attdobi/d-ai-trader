"""Policy graph — the versioned, human-readable knowledge graph behind each agent's prompt.

Every prompt_versions row (system_prompt, user_prompt_template, strategy_directives, soul,
memory) is decomposed into a directory of Markdown node files + edges.json + manifest.json,
RUSH-style (see /Users/adobi/RUSH), under agents/<dir>/policy-graph/<config_hash>/v<N>/.

Fidelity contract ("same bytes"): the three compiled fields are partitioned into contiguous
slices (sep_before + body + sep_after); compile is plain concatenation in manifest.compile_order,
so compile(decompose(row)) reproduces the stored text byte-for-byte. The live trader keeps
reading prompt_versions; the graph is derived beside it (Phase 1) and, in Phase 2, the RL loop
edits node files and compiles them back into prompt_versions rows.

Import rules for this package: stdlib only, plus `sqlalchemy.text` in service/routes/health.
NEVER import `config` and NEVER read os.environ here — config_hash and repo_root are explicit
parameters everywhere (two OS processes write these dirs and mutate the env at runtime).
"""

BUILDER_VERSION = 1

from .model import (  # noqa: E402,F401
    AGENT_PREFIX, AGENT_DIR, AGENT_LABEL, FIELDS, COMPILED_FIELDS, TEMPLATE_FIELDS,
    Node, Edge, Slice, GraphBuild, Version, InheritedText, RowMeta,
)
