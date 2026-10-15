"""Compare FP32 model tensors and visible detections independently of TopK tie order."""
import numpy as np


def compare_detections(reference, actual, threshold=0.5):
    from scipy.optimize import linear_sum_assignment

    ref_labels, ref_boxes, ref_scores = (np.asarray(x)[0] for x in reference)
    labels, boxes, scores = (np.asarray(x)[0] for x in actual)
    for value in (*reference, *actual):
        if not np.isfinite(value).all():
            raise AssertionError("Non-finite inference output")
    selected_ref = ref_scores > threshold
    selected = scores > threshold
    if int(selected_ref.sum()) != int(selected.sum()):
        raise AssertionError("Detection count differs at the configured threshold")
    max_box_error = max_score_error = 0.0
    for label in np.union1d(ref_labels[selected_ref], labels[selected]):
        r = np.flatnonzero(selected_ref & (ref_labels == label))
        a = np.flatnonzero(selected & (labels == label))
        if len(r) != len(a):
            raise AssertionError("Detection classes differ at the configured threshold")
        # Match boxes within each class; almost equal scores may reorder TopK.
        cost = np.abs(ref_boxes[r, None, :] - boxes[None, a, :]).max(axis=2)
        rows, cols = linear_sum_assignment(cost)
        rb, ab = ref_boxes[r[rows]], boxes[a[cols]]
        rs, actual_scores = ref_scores[r[rows]], scores[a[cols]]
        np.testing.assert_allclose(ab, rb, atol=0.05, rtol=1e-4)
        np.testing.assert_allclose(actual_scores, rs, atol=1e-5, rtol=1e-3)
        if len(rows):
            max_box_error = max(max_box_error, float(np.abs(ab - rb).max()))
            max_score_error = max(max_score_error, float(np.abs(actual_scores - rs).max()))
    return {
        "detectionsAboveThreshold": int(selected.sum()),
        "boxMaxAbsErrorPixels": max_box_error,
        "scoreMaxAbsError": max_score_error,
        "allTopKLabelsSameOrder": bool(np.array_equal(ref_labels, labels)),
        "passed": True,
    }


def compare_raw(reference, actual):
    # All queries/classes are checked, including candidates below the UI threshold.
    for value in (*reference, *actual):
        if not np.isfinite(value).all():
            raise AssertionError("Non-finite raw model tensor")
    np.testing.assert_allclose(actual[0], reference[0], atol=2e-4, rtol=1e-4)
    # 1e-4 normalized units is 0.064 pixels at the network's 640px input.
    # Visible boxes are independently checked in original-image pixel units above.
    np.testing.assert_allclose(actual[1], reference[1], atol=1e-4, rtol=1e-4)
    return {
        "logitsMaxAbsError": float(np.abs(actual[0] - reference[0]).max()),
        "normalizedBoxesMaxAbsError": float(np.abs(actual[1] - reference[1]).max()),
    }
