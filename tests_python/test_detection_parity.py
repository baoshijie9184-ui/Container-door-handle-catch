import numpy as np
import pytest
from script.shell.detection_parity import compare_detections, compare_raw


def prediction(labels, boxes, scores):
    return [np.asarray([labels]), np.asarray([boxes], dtype=np.float32), np.asarray([scores], dtype=np.float32)]


def test_equal_score_reordering_preserves_detection_meaning():
    ref=prediction([0,1], [[0,0,50,50],[60,60,90,90]], [.8,.8])
    actual=prediction([1,0], [[60,60,90,90],[0,0,50,50]], [.8,.8])
    result=compare_detections(ref,actual)
    assert result['passed'] and not result['allTopKLabelsSameOrder']


@pytest.mark.parametrize('actual', [
    prediction([0,2], [[0,0,50,50],[60,60,90,90]], [.8,.8]),
    prediction([0,1], [[0,0,50,50],[60,60,90,90]], [.8,.49]),
    prediction([0,1], [[0,0,50,50],[60,60,100,100]], [.8,.8]),
])
def test_class_count_and_box_changes_are_rejected(actual):
    ref=prediction([0,1], [[0,0,50,50],[60,60,90,90]], [.8,.8])
    with pytest.raises(AssertionError):
        compare_detections(ref,actual)


def test_raw_gate_catches_changes_even_below_threshold():
    ref=[np.zeros((1,300,6),dtype=np.float32), np.ones((1,300,4),dtype=np.float32)]
    changed=[ref[0].copy(),ref[1].copy()]
    changed[0][0,299,5]=.1
    with pytest.raises(AssertionError):
        compare_raw(ref,changed)


def test_finite_fp32_fusion_roundoff_is_accepted_but_nan_is_not():
    ref=[np.zeros((1,300,6),dtype=np.float32), np.full((1,300,4),.1,dtype=np.float32)]
    changed=[ref[0].copy(),ref[1].copy()]
    changed[1][0,0,0]+=2.3e-5
    assert compare_raw(ref,changed)['normalizedBoxesMaxAbsError']<3e-5
    changed[0][0,0,0]=float('nan')
    with pytest.raises(AssertionError,match='Non-finite'):
        compare_raw(ref,changed)
