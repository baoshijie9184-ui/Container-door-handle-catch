import hashlib
import json
from io import BytesIO

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper
from PIL import Image

from onnx_detection_engine import OnnxDetectionEngine


def fixture_model(tmp_path, labels=None, scores=None):
    outputs = {
        'labels': np.asarray([[0, 1]] if labels is None else labels, dtype=np.int64),
        'boxes': np.asarray([[[-10., 5., 90., 95.], [15., 10., 60., 50.]]], dtype=np.float32),
        'scores': np.asarray([[.8, .95]] if scores is None else scores, dtype=np.float32),
    }
    graph = helper.make_graph([
        helper.make_node('Constant', [], [name], value=numpy_helper.from_array(value))
        for name, value in outputs.items()
    ], 'test-export-contract', [
        helper.make_tensor_value_info('images', TensorProto.FLOAT, [1, 3, 640, 640]),
        helper.make_tensor_value_info('orig_target_sizes', TensorProto.INT64, [1, 2]),
    ], [helper.make_tensor_value_info(name, TensorProto.INT64 if name=='labels' else TensorProto.FLOAT, list(value.shape)) for name, value in outputs.items()])
    model=helper.make_model(graph, opset_imports=[helper.make_opsetid('',17)], ir_version=8)
    path=tmp_path/'model.onnx'
    onnx.save(model,path)
    manifest={'schemaVersion':1,'modelFile':path.name,'onnxSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'classNames':['Normal','Bent','Deformed','Rusty','Missing','Compromised'],
              'inputSize':[640,640],'mean':[.485,.456,.406],'std':[.229,.224,.225]}
    target=tmp_path/'manifest.json'
    target.write_text(json.dumps(manifest),encoding='utf-8')
    return target, path


def test_real_onnx_outputs_are_sorted_filtered_and_clamped(tmp_path):
    manifest,_=fixture_model(tmp_path)
    engine=OnnxDetectionEngine(manifest)
    image=Image.new('RGB',(80,70),'white')
    content=BytesIO();image.save(content,format='JPEG')
    annotated, results=engine.detect_bytes(content.getvalue(),.85)
    assert annotated.size==(80,70)
    assert len(results)==1 and results[0]['label']=='Bent'
    _, results=engine.predict(image,.5)
    assert results[1]['box']==[0.,5.,80.,70.]
    assert np.allclose(engine.prepare(image)[0,:,0,0], (np.ones(3)-[.485,.456,.406])/[.229,.224,.225])


def test_tampered_model_is_rejected_before_startup(tmp_path):
    manifest,model=fixture_model(tmp_path)
    model.write_bytes(model.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='SHA-256'):
        OnnxDetectionEngine(manifest)


@pytest.mark.parametrize('labels,scores,message', [([[0,6]],None,'class index'),(None,[[.8,float('nan')]],'Non-finite'),(None,[[.8,1.1]],'probability')])
def test_invalid_outputs_fail_readiness(tmp_path, labels, scores, message):
    manifest,_=fixture_model(tmp_path,labels,scores)
    with pytest.raises(ValueError,match=message):
        OnnxDetectionEngine(manifest)


def test_invalid_threshold_is_not_silently_accepted(tmp_path):
    manifest,_=fixture_model(tmp_path)
    engine=OnnxDetectionEngine(manifest)
    with pytest.raises(ValueError,match='threshold'):
        engine.predict(Image.new('RGB',(20,20)),float('nan'))
