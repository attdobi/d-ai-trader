"""Historical citations to retired memories must not look like current errors."""
from sqlalchemy import create_engine, text

from policy_router.panel import _citation_context


def test_retired_citations_are_explained_without_rewriting_raw_retention():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE policy_router_decisions(config_hash TEXT,run_id TEXT,node_id TEXT,choice TEXT)"))
        conn.execute(text("CREATE TABLE policy_graph_hits(config_hash TEXT,run_id TEXT,node_id TEXT,cited BOOLEAN)"))
        conn.execute(text("CREATE TABLE decider_memory(config_hash TEXT,id INTEGER,active BOOLEAN,content TEXT)"))
        for run in ("old1", "old2"):
            conn.execute(text("INSERT INTO policy_router_decisions VALUES ('h',:r,'DA.ltm.42','exclude')"), {"r": run})
            conn.execute(text("INSERT INTO policy_graph_hits VALUES ('h',:r,'DA.ltm.42',TRUE)"), {"r": run})
        conn.execute(text("INSERT INTO decider_memory VALUES ('h',42,FALSE,:body)"),
                     {"body": "IF EVENT CALENDAR shows MACRO WINDOW: YES THEN pass."})
        conn.execute(text("INSERT INTO decider_memory VALUES ('other',42,TRUE,'keep this')"))
    context = _citation_context(engine, "h", [{"run_id": "old1"}, {"run_id": "old2"}])
    assert context == [{"node_id": "DA.ltm.42", "cited": 2, "router_kept": 0, "active": False, "policy_conflict": True}]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM policy_router_decisions WHERE choice='exclude' ")).scalar() == 2
    engine.dispose()
