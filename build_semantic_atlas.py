#!/usr/bin/env python3
"""Build the local frozen semantic landscape; no hosted API, broker or trading."""
import argparse
import contextlib
import io
import json
from pathlib import Path

from policy_graph.model import AGENT_DIR
from policy_graph.semantic_atlas import build_atlas, MAX_POINTS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-hash',required=True)
    parser.add_argument('--agent',choices=[*AGENT_DIR,'all'],default='all')
    parser.add_argument('--days',type=int,default=90)
    parser.add_argument('--refit',action='store_true',help='Explicitly replace the frozen atlas with a new fitted reference')
    parser.add_argument('--lexical-fallback',action='store_true',help='Allow explicitly labeled word-feature t-SNE if local semantic embeddings are unavailable')
    parser.add_argument('--embedding-budget',type=float,default=60)
    parser.add_argument('--max-points',type=int,default=MAX_POINTS,help='Bound the fitted/extended corpus, at most 700 points')
    args=parser.parse_args()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from config import engine, IS_MARGIN_ACCOUNT
    if engine.dialect.name!='postgresql':
        raise RuntimeError('The existing Postgres database is required')
    from policy_graph import service
    from policy_graph.learning import history
    from policy_graph.taxonomy import observation_inventory
    from policy_graph.themes import annotate
    from policy_router.embed import EmbedCache,EmbeddingClient
    root=Path(__file__).resolve().parent
    inventory=observation_inventory(engine,args.config_hash,days=args.days,limit=150)
    if not inventory.get('available'):
        raise RuntimeError('Scoped source observations unavailable')
    shared=root/'agents'/'decider'/'policy-router'/'embed-cache.sqlite3'
    embedder=EmbeddingClient(cache=EmbedCache(shared),timeout=15)
    agents=list(AGENT_DIR) if args.agent=='all' else [args.agent]
    for agent in agents:
        ctx=service._Ctx(engine,args.config_hash,root,bool(IS_MARGIN_ACCOUNT))
        landmarks,_=history(ctx,agent)
        observations=inventory.get('observations') or []
        annotate(landmarks,[],config_hash=args.config_hash,observations=observations,
                 observation_counts=inventory.get('topic_counts') or {})
        path=root/'agents'/AGENT_DIR[agent]/'policy-router'/args.config_hash/'semantic-atlas.json'
        before=embedder.calls
        result=build_atlas(landmarks,observations,path,config_hash=args.config_hash,agent=agent,embedder=embedder,
                           force=args.refit,allow_lexical=args.lexical_fallback,embedding_budget_s=args.embedding_budget,
                           max_points=args.max_points)
        print(json.dumps({key:result[key] for key in ('id','method','embedding_model','reference_count','pending','fitted_with')}
                         | {'agent':agent,'points':len(result['points']),'clusters':len(result['clusters']),
                            'local_embedding_requests':embedder.calls-before,'hosted_api_requests':0},default=str),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'message':'Local atlas build did not complete; provider and connection diagnostics withheld.'}))
        raise SystemExit(1)
