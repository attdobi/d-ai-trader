"""Which stored fields actually reach each agent's production call. No config I/O."""
from urllib.parse import urlencode

from policy_graph.model import AGENT_PREFIX, FIELDS


def prompt_contract(agent, version=None):
    if agent not in AGENT_PREFIX:
        raise ValueError("Unknown agent")
    fields = {field: {"used": True, "note": "Included in the production prompt."} for field in FIELDS}
    if agent == "FeedbackAgent":
        for field in FIELDS:
            fields[field] = {"used": field == "soul", "note": (
                "Included with the code-owned weekly review instructions." if field == "soul" else
                "Reference/manual template. The automatic weekly review uses code-owned instructions and JSON schema.")}
        note = ("Weekly review uses code-owned system, task and JSON instructions plus this version's Soul. "
                "Feedback is archived for human review; it cannot activate a rule or memory. "
                "The legacy manual review uses the stored system and user templates.")
    elif agent == "SummarizerAgent":
        note = ("All five fields reach the summarizer. Headlines and insights reach the Decider; "
                "catalyst cards are retained for audit. Put essential event facts and uncertainty in insights.")
    elif agent == "CompanyExtractionAgent":
        note = "All five fields reach entity extraction. Its output is a company/symbol array, not a trading decision."
    else:
        note = ("All five fields reach the Decider alongside code-owned controls and per-cycle inputs. "
                "Current approved rules govern; historical memory and unreviewed feedback supply evidence.")
    query = {"agent": agent, "mode": "runtime", "field": "all"}
    if version is not None:
        query["version"] = int(version)
    return {"agent": agent, "fields": fields, "runtime_note": note,
            "compiled_runtime_url": "/api/policy-graph/compiled?" + urlencode(query)}
