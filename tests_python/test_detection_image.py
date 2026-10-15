import numpy as np
import pytest
from PIL import Image
from detection_image import annotate


def test_six_class_mapping_clipping_and_threshold():
    image=Image.new('RGB',(100,80))
    labels=np.arange(6)[None]
    boxes=np.tile([-10,-5,120,90],(1,6,1))
    scores=np.array([[.9,.8,.7,.6,.5,.4]])
    annotated,result=annotate(image,labels,boxes,scores,.5)
    assert [d['label'] for d in result]==['Normal','Bent','Deformed','Rusty']
    assert all(d['box']==[0.,0.,100.,80.] for d in result)
    assert annotated.size==image.size
    assert image.getpixel((0,0))==(0,0,0)


@pytest.mark.parametrize('labels,boxes,scores',[
    ([[6]],[[[1,2,3,4]]],[[.9]]),
    ([[0]],[[[float('nan'),2,3,4]]],[[.9]]),
    ([[0]],[[[1,2,3,4]]],[[1.1]]),
])
def test_invalid_model_output_is_rejected(labels,boxes,scores):
    with pytest.raises(ValueError):
        annotate(Image.new('RGB',(100,80)),labels,boxes,scores,.5)
