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


def test_saved_labels_use_distinct_chinese_glyphs_and_keep_model_labels():
    from detection_image import _song, LABEL_STYLE
    font = _song(36)
    chars = set(''.join(label for label, _ in LABEL_STYLE.values()))
    assert len({bytes(font.getmask(char)) for char in chars}) == len(chars)
    image = Image.new('RGB', (800,600),'#dddddd')
    boxes = [[[20,80,120,180],[570,0,800,90]]]
    marked, result = annotate(image, [[1,5]], boxes, [[.923,.879]], .5)
    assert [item['label'] for item in result] == ['Bent','Compromised']
    assert result[0]['box'] == [20.,80.,120.,180.]
    assert marked.size == image.size
    # High-contrast label exists above the first box, even on a light source.
    colors = marked.crop((20,20,220,80)).getcolors(12000)
    assert any(color == (255,255,255) and n>10 for n,color in colors)
    assert any(color == (133,70,0) and n>200 for n,color in colors)
