"""Evaluation evidence must reject incomplete or ambiguous provider judgements."""
import importlib.util
import json
from pathlib import Path
import unittest

SPEC=importlib.util.spec_from_file_location('semantic_eval',Path(__file__).resolve().parents[1]/'script/diagnostics/memory-semantic-eval.py')
evaluation=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


class SemanticEvidenceTest(unittest.TestCase):
    def test_original_baseline_and_independent_examples_are_preserved(self):
        self.assertEqual(16,sum(len(c['candidates']) for c in evaluation.CASES))
        self.assertEqual('RELATED',evaluation.CASES[2]['candidates'][3][1])
        self.assertEqual(16,sum(len(c['candidates']) for c in evaluation.HOLDOUT_CASES))
        self.assertFalse({c['source'] for c in evaluation.CASES}&{c['source'] for c in evaluation.HOLDOUT_CASES})

    def test_complete_response_can_be_reordered(self):
        supplied=evaluation.parse_labels('{"labels":[{"id":"C1","label":"RELATED"},{"id":"C0","label":"CONFLICT"}]}',[{'id':'C0'},{'id':'C1'}])
        self.assertEqual({'C0':'CONFLICT','C1':'RELATED'},supplied)

    def test_ambiguous_or_partial_results_are_never_scored_as_complete(self):
        bad=[{'labels':[]}, {'labels':[{'id':'C0','label':'RELATED'}]},
             {'labels':[{'id':'C0','label':'RELATED'},{'id':'C0','label':'CONFLICT'}]},
             {'labels':[{'id':'C0','label':'RELATED'},{'id':'C2','label':'DISTINCT'}]},
             {'labels':[{'id':'C0','label':'RELATED'},{'id':'C1','label':'AUTHORIZED'}]},
             {'labels':[{'id':'C0','label':'RELATED'},{'id':'C1','label':'DISTINCT','execute':True}]},
             {'labels':{},'decision':'delete'}, [], {'labels':[None]}]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):
                evaluation.parse_labels(json.dumps(value),[{'id':'C0'},{'id':'C1'}])


if __name__=='__main__':unittest.main()
