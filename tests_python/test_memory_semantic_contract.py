"""Protocol validation only: no provider, embeddings, or persistent memory writes."""
import json
import pytest
from memory_service.duplicate_review import semantic_labels

SOURCE = '门把手涂层检验标准要求人工复核'
PENDING = [{'id': 'C0', 'text': '门把手涂层检验标准需要人工复核'}]

def decision(**changes):
    row = dict(id='C0', label='DUPLICATE', topicRelation='SAME_OBJECT',
               equivalent=True, incompatible=False,
               sourceAnchor='门把手涂层检验标准', candidateAnchor='门把手涂层检验标准')
    row.update(changes)
    return row

@pytest.mark.parametrize('changes', [
    {'sourceAnchor': '不存在的证据'}, {'candidateAnchor': '另一份资料'},
    {'sourceAnchor': ''}, {'sourceAnchor': '字' * 81},
    {'equivalent': 'true'}, {'incompatible': True},
    {'topicRelation': 'UNRELATED'}, {'label': 'CONFLICT'},
    {'id': 'foreign-id'}, {'unexpected': 'instruction'},
])
def test_inconsistent_or_unbound_model_answers_are_rejected(changes):
    with pytest.raises(ValueError):
        semantic_labels(json.dumps({'labels': [decision(**changes)]}), SOURCE, PENDING)

@pytest.mark.parametrize('rows', [[], [decision(), decision()], [{'id': 'C0', 'label': 'DUPLICATE'}]])
def test_missing_duplicated_and_legacy_decisions_are_rejected(rows):
    with pytest.raises(ValueError):
        semantic_labels(json.dumps({'labels': rows}), SOURCE, PENDING)

@pytest.mark.parametrize('changes,expected', [
    ({}, 'DUPLICATE'),
    ({'equivalent': False, 'incompatible': True, 'label': 'CONFLICT'}, 'CONFLICT'),
    ({'equivalent': False, 'label': 'RELATED'}, 'RELATED'),
    ({'equivalent': False, 'topicRelation': 'UNRELATED', 'label': 'DISTINCT'}, 'DISTINCT'),
    ({'equivalent': False, 'topicRelation': 'UNCERTAIN', 'label': 'UNSURE',
      'sourceAnchor': '', 'candidateAnchor': ''}, 'UNSURE'),
])
def test_consistent_dimensions_produce_label_without_persisting_private_anchors(changes, expected):
    result = semantic_labels(json.dumps({'labels': [decision(**changes)]}), SOURCE, PENDING)
    assert result['C0']['label'] == expected
    assert 'sourceAnchor' not in result['C0']
    assert 'candidateAnchor' not in result['C0']
