#!/usr/bin/env python3
"""Review a bounded saved-news sample once; never changes trading policy."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

from policy_graph.taxonomy import observation_inventory, proposal_records, proposal_request, validate_proposal
from policy_graph.taxonomy_review import latest_review, save_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-hash',required=True)
    parser.add_argument('--run',action='store_true',help='One explicitly requested paid Sol review, without retries')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    os.environ['CURRENT_CONFIG_HASH']=args.config_hash
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import config
    if config.engine.dialect.name!='postgresql':
        raise RuntimeError('Existing Postgres required')
    inventory=observation_inventory(config.engine,args.config_hash)
    records=proposal_records(inventory)
    if not inventory['available'] or not records:
        raise RuntimeError('Scoped source observations unavailable')
    source_hash=hashlib.sha256(json.dumps([(r['record_id'],r.get('source_sha256')) for r in records],separators=(',',':')).encode()).hexdigest()
    result={'paid_request':False,'taxonomy_version':inventory['taxonomy_version'],
            'source_row_counts':inventory['source_row_counts'],'safe_record_count':inventory['safe_record_count'],
            'topic_counts':inventory['topic_counts'],'sample_records':len(records),
            'source_hash':source_hash,'status':'preview'}
    previous=latest_review(config.engine,args.config_hash)
    if args.run and previous and previous['source_hash']==source_hash:
        result.update(status='unchanged_source_already_reviewed',review_id=previous['id'])
    elif args.run:
        from openai import OpenAI
        request=proposal_request(records)
        client=OpenAI(api_key=config.api_key,base_url='https://api.openai.com/v1',timeout=60,max_retries=0)
        response=client.chat.completions.create(model='gpt-6.1-sol',
            messages=[{'role':'system','content':request['system_prompt']},{'role':'user','content':request['user_prompt']}],
            response_format={'type':'json_schema','json_schema':{'name':'market_taxonomy_review','strict':True,'schema':request['response_schema']}},
            reasoning_effort='medium',max_completion_tokens=6000,store=False)
        manager=config.PromptManager(client,None,run_id='taxonomy-'+source_hash[:16])
        manager._record_api_usage('TaxonomyReviewAgent',response.model,response)
        if response.choices[0].finish_reason!='stop':
            raise RuntimeError('Incomplete taxonomy review; no automatic retry')
        review=validate_proposal(json.loads(response.choices[0].message.content),records)
        usage=manager.last_usage() or {}
        ident=save_review(config.engine,args.config_hash,review,model=response.model,usage=usage,cost_usd=usage.get('cost_usd'))
        result.update(paid_request=True,status=review['status'],review_id=ident,model=response.model,
                      cost_usd=usage.get('cost_usd'),usage=usage,review=review)
    if args.output:
        args.output.write_text(json.dumps(result,ensure_ascii=False,default=str,indent=2)+'\n')
        args.output.chmod(0o600)
    print(json.dumps(result,ensure_ascii=False,default=str,indent=2))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'message':'Taxonomy review did not complete; provider/connection diagnostics withheld.'}))
        raise SystemExit(1)
