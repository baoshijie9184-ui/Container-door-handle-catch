"""Bounded synthetic classifier checks using the owned candidate's native SDK and model."""
import argparse
import ast
import inspect
import json
from pathlib import Path
import runpy
import subprocess

from candidate_environment import CandidateEnvironment, probe_source, timestamp


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--model',choices=['qwen3.8-flash','qwen3.8-max-0902'],
                        help='Read-only Bailian classifier variant; does not change candidate extraction')
    parser.add_argument('--local-prompt',action='store_true',help='Read-only prompt variant from local reviewed source; never updates the candidate')
    parser.add_argument('--expanded',action='store_true',help='Add sixteen new fixed validation relationships')
    args=parser.parse_args(argv)
    if not args.execute:parser.error('Explicit bounded model calls must be requested')
    api=runpy.run_path(str(Path(__file__).with_name('memory-semantic-eval.py')))
    cases=api['CASES']+api['HOLDOUT_CASES']
    if args.expanded:cases+=api['VALIDATION_CASES']
    override=None
    if args.local_prompt:
        source=Path(__file__).resolve().parents[2]/'memory_service/duplicate_review.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        values={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'PROMPT','PROMPT_VERSION'}}
        override={'prompt':values['PROMPT'],'version':values['PROMPT_VERSION']}
    env=CandidateEnvironment(args.candidate_report,args.directory)
    report={'startedAt':timestamp(),'project':env.project,'release':env.candidate['release'],
            'sourceSha256':env.candidate['sourceSha256'],'passed':False,'callsLimit':len(cases),
            'readOnlyModelVariant':args.model,
            'localPromptVariant':args.local_prompt,'expandedValidation':args.expanded,
            'scope':'fixed synthetic relationships; no memory or vector writes and no retry'}
    env.write('result.json',report)
    child='''import hashlib,json
from types import SimpleNamespace
import main as bridge
from duplicate_review import PROMPT,PROMPT_VERSION,model_metrics,review_request_budget
from mem0.utils.factory import LlmFactory
'''+inspect.getsource(api['parse_labels'])+'''
cases=CASES
candidate_prompt_version=PROMPT_VERSION
candidate_prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest()
override=PROMPT_OVERRIDE
if override:PROMPT,PROMPT_VERSION=override['prompt'],override['version']
if PROMPT_VERSION>=6:
    from duplicate_review import semantic_labels
config=bridge.get_memory_config()['llm']
assert config['config']['model'] in {'qwen3.8-flash','qwen3.8-max-0902'}
candidate_model=config['config']['model']
requested=MODEL
if requested:config['config']['model']=requested
llm=bridge.configure_llm_provider(LlmFactory.create(config['provider'],config['config']))
document={'model':config['config']['model'],'candidateExtractionModel':candidate_model,'promptVersion':PROMPT_VERSION,
          'candidatePromptVersion':candidate_prompt_version,'candidatePromptSha256':candidate_prompt_sha256,
          'promptSha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
          'datasetSha256':hashlib.sha256(json.dumps(cases,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
          'results':[],'retryCount':0,'gatePassed':False}
try:
    for case in cases:
        row={'id':case['id'],'status':'UNAVAILABLE','checks':[]};metrics={}
        candidates=[{'id':'C'+str(i),'text':text} for i,(text,_) in enumerate(case['candidates'])]
        try:
            with review_request_budget(llm),model_metrics(SimpleNamespace(llm=llm),metrics):
                response=llm.generate_response(messages=[{'role':'system','content':PROMPT},
                    {'role':'user','content':json.dumps({'source':case['source'],'candidates':candidates},ensure_ascii=False)}],
                    response_format={'type':'json_object'})
            if PROMPT_VERSION>=6:
                decisions=semantic_labels(response,case['source'],candidates)
                labels={id:decision['label'] for id,decision in decisions.items()}
                row['decisionValidation']='STRUCTURED_V6'
            else:labels=parse_labels(response,candidates)
            row['checks']=[{'id':'C'+str(i),'expected':expected,'actual':labels['C'+str(i)],
                            'passed':labels['C'+str(i)]==expected} for i,(_,expected) in enumerate(case['candidates'])]
            row['status']='PASS' if all(c['passed'] for c in row['checks']) else 'MISMATCH'
        except Exception as error:row['errorType']=type(error).__name__
        row['metrics']=metrics;document['results'].append(row)
        print(json.dumps({'checkpoint':document}),flush=True)
        if row['status']=='UNAVAILABLE':break
    document['gatePassed']=len(document['results'])==len(cases) and all(r['status']=='PASS' for r in document['results'])
finally:llm.client.close()
print(json.dumps({'result':document}),flush=True)
'''.replace('cases=CASES','cases='+repr(cases)).replace('requested=MODEL','requested='+repr(args.model)).replace('override=PROMPT_OVERRIDE','override='+repr(override))
    code=probe_source(env.candidate).replace("print('owned-candidate-ready')",'')+'''
ids=subprocess.check_output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,
    '--filter','label=com.docker.compose.service=mem0']).decode().split();assert len(ids)==1
row=json.loads(subprocess.check_output(['docker','inspect',ids[0]]))[0]
assert row['Config']['Labels'].get('io.doorhandle.rehearsal')==project
result=subprocess.run(['docker','exec','-i',ids[0],'python','-'],input=CHILD,text=True,capture_output=True,timeout=420)
# Only the deliberately bounded classifier protocol is emitted, never private logs.
for line in result.stdout.splitlines():
    try:value=json.loads(line)
    except ValueError:continue
    if isinstance(value,dict) and set(value) in ({'checkpoint'},{'result'}):print(json.dumps(value),flush=True)
assert result.returncode==0
'''.replace('input=CHILD','input='+repr(child))
    try:
        with env:
            process=subprocess.Popen(env.ssh+['doorhandle-bj','python3 -'],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:output,_=process.communicate(code,timeout=450)
            except subprocess.TimeoutExpired:
                process.kill();process.communicate(timeout=10)
                raise RuntimeError('Classifier outcome unavailable; do not automatically retry') from None
            for line in output.splitlines():
                value=json.loads(line)
                if 'checkpoint' in value:report['evaluation']=value['checkpoint']
                if 'result' in value:
                    report['evaluation']=value['result'];report['passed']=value['result']['gatePassed']
                env.write('result.json',report)
            if process.returncode:raise RuntimeError('Owned classifier stopped; no calls are retried')
            if not report['passed']:raise AssertionError('Synthetic relationship gate did not pass')
    except Exception as error:
        report['errorType']=type(error).__name__;raise
    finally:
        report['finishedAt']=timestamp();env.write('result.json',report)


if __name__=='__main__':main()
