"""Safety checks for the opt-in load driver; these are not capacity results."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script/diagnostics'))
spec=importlib.util.spec_from_file_location('candidate_soak',ROOT/'script/diagnostics/candidate-soak-acceptance.py')
soak=importlib.util.module_from_spec(spec);spec.loader.exec_module(soak)


@pytest.mark.parametrize('options', [[], ['--execute','--seconds','60'],
    ['--execute','--seconds','7201'], ['--execute','--accounts','4'],
    ['--execute','--accounts','33']])
def test_opt_in_and_minimum_scope_are_required_before_any_environment_use(monkeypatch,tmp_path,options):
    target=tmp_path/'never-created'
    monkeypatch.setattr(sys,'argv',['soak','--candidate-report',str(tmp_path/'missing.json'),'--directory',str(target),*options])
    monkeypatch.setattr(soak,'CandidateEnvironment',lambda *args:pytest.fail('An invalid load request reached the environment'))
    with pytest.raises(SystemExit) as error:soak.main()
    assert error.value.code==2 and not target.exists()


def test_production_identity_is_rejected_without_starting_ssh(monkeypatch,tmp_path):
    receipt=tmp_path/'production.json';receipt.write_text(json.dumps({'passed':True,'kept':True,'productionChanged':False,'project':'doorhandlecatch-monolith'}))
    target=tmp_path/'never-created'
    monkeypatch.setattr(sys,'argv',['soak','--candidate-report',str(receipt),'--directory',str(target),'--execute'])
    monkeypatch.setattr(soak.subprocess,'run',lambda *args,**kwargs:pytest.fail('Production must never be probed by this load driver'))
    with pytest.raises(ValueError,match='Candidate project'):soak.main()
    assert not target.exists()
