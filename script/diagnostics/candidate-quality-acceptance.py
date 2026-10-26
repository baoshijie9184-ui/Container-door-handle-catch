"""Run the existing two-task CPU PTH/quality/report demo only through a verified owned candidate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from candidate_environment import CandidateEnvironment, timestamp

ROOT=Path(__file__).resolve().parents[2]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--execute',action='store_true',help='Creates two private demo tasks and their own report; uploads unique test objects and runs CPU PTH')
    parser.add_argument('--resume-from',help='Continue only the saved two-task checkpoint after normal release and before report creation')
    args=parser.parse_args(argv)
    if not args.execute:parser.error('Explicit --execute is required')
    with CandidateEnvironment(args.candidate_report,args.directory) as candidate:
        evidence={'startedAt':timestamp(),'project':candidate.project,'release':candidate.candidate['release'],
            'sourceSha256':candidate.candidate['sourceSha256'],'passed':False,
            'scope':'two newly created demo tasks only; shared OSS receives new task-scoped test objects; no existing task mutation'}
        candidate.write('quality-admission.json',evidence)
        workflow=candidate.out/'workflow'
        resume=[]
        if args.resume_from:
            source=Path(args.resume_from).resolve(strict=True)
            if not source.is_relative_to(ROOT/'work') or source.name!='result.json' or source.parent.name!='workflow':
                raise ValueError('Resume requires a prior candidate workflow receipt')
            prior=json.loads((source.parent.parent/'quality-admission.json').read_text(encoding='utf8'))
            if any(prior.get(key)!=evidence[key] for key in ('project','release','sourceSha256')):
                raise ValueError('Resume receipt belongs to another candidate')
            resume=['--resume-from',str(source)]
            evidence['resumeSource']=str(source)
        environment={**os.environ,'DOORHANDLE_DEMO_PASSWORD':os.environ.get('DOORHANDLE_DEMO_PASSWORD','123456')}
        try:
            result=subprocess.run([sys.executable,str(ROOT/'script/diagnostics/quality-positive-acceptance.py'),
                '--execute','--directory',str(workflow),'--base-url',candidate.base,*resume],
                cwd=ROOT,env=environment,timeout=1800,check=False)
            evidence['exitCode']=result.returncode
            receipt=json.loads((workflow/'result.json').read_text(encoding='utf8'))
            expected_tasks={'normal-release','rework-recheck'}
            evidence.update(passed=bool(result.returncode==0 and receipt.get('passed') is True and set(receipt.get('tasks',{}))==expected_tasks),
                            taskCount=len(receipt.get('tasks',{})),checks=len(receipt.get('checks',[])))
            if not evidence['passed']:raise RuntimeError('Candidate demo workflow did not pass; inspect its existing receipts before any retry')
        finally:
            evidence['finishedAt']=timestamp()
            candidate.write('quality-admission.json',evidence)
        print(json.dumps({key:evidence[key] for key in ('passed','taskCount','checks','project')}),flush=True)


if __name__=='__main__':main()
