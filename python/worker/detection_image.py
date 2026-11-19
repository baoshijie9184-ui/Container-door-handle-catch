"""Shared image validation and annotation for native PyTorch inference."""
from functools import lru_cache
from pathlib import Path
import math
import numpy as np
from PIL import ImageDraw, ImageFont

NAMES = ['Normal','Bent','Deformed','Rusty','Missing','Compromised']


# Only the raster labels are translated. Structured model labels stay canonical.
LABEL_STYLE = {
    'Normal': ('正常', '#215895'), 'Bent': ('弯曲', '#854600'),
    'Deformed': ('形变', '#a13016'), 'Rusty': ('锈蚀', '#633f25'),
    'Missing': ('缺失', '#a91c42'), 'Compromised': ('结构损伤', '#65349a'),
}
FONT_FILE = Path(__file__).resolve().parent / 'fonts' / 'annotation-song.otf'


@lru_cache(maxsize=48)
def _song(size):
    return ImageFont.truetype(str(FONT_FILE), size)


def _overlap(rect, other):
    return (max(0, min(rect[2], other[2]) - max(rect[0], other[0])) *
            max(0, min(rect[3], other[3]) - max(rect[1], other[1])))


def render_detections(image, detections):
    output = image.convert('RGB').copy()
    if not detections:
        return output
    draw = ImageDraw.Draw(output)
    width, height = output.size
    scale = min(width, height)
    font_size = max(12, min(180, round(scale * .050)))
    line = max(2, round(font_size * .105))
    pad = max(2, round(font_size * .13))
    labels = []
    for target in detections:
        word, color = LABEL_STYLE.get(target['label'], ('未知', '#394457'))
        x0, y0, x1, y1 = target['box']
        frame = (max(0,min(width-1,round(x0))), max(0,min(height-1,round(y0))),
                 max(0,min(width-1,round(x1))), max(0,min(height-1,round(y1))))
        draw.rectangle(frame, outline='white', width=line+2)
        draw.rectangle(frame, outline=color, width=line)
        labels.append((frame, f"{word} {target['score']:.0%}", color))

    placed = []
    for frame, text, color in labels:
        x0, y0, x1, y1 = frame
        font = _song(font_size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right-left+2*pad > width:
            font = _song(max(1, int(font_size * max(1,width-2*pad) / max(1,right-left))))
            left, top, right, bottom = draw.textbbox((0,0), text, font=font)
        w, h = right-left+2*pad, bottom-top+2*pad
        anchors = [(x0,y0-h), (x0,y1+1), (x1-w,y0-h), (x1-w,y1+1), (x0,y0), (x1-w,y1-h)]
        for step in (2,3):
            anchors.extend(((x0,y0-h*step),(x0,y1+1+h*(step-1))))
        candidates = []
        for x,y in anchors:
            x, y = max(0,min(width-w,x)), max(0,min(height-h,y))
            candidates.append((x,y,x+w,y+h))
        rect = min(candidates, key=lambda r: (sum(_overlap(r,p) for p in placed), _overlap(r,frame)))
        placed.append(rect)
        x,y = rect[:2]
        draw.rectangle((x,y,rect[2]-1,rect[3]-1),fill=color)
        draw.text((x+pad-left,y+pad-top),text,font=font,fill='white')
    return output


def annotate(image, labels, boxes, scores, threshold):
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Detection threshold must be between zero and one')
    labels,boxes,scores=(np.asarray(x) for x in (labels,boxes,scores))
    if labels.ndim!=2 or labels.shape[0]!=1 or scores.shape!=labels.shape or boxes.shape!=(*labels.shape,4):
        raise ValueError('Malformed detection output shapes')
    if not all(np.isfinite(x).all() for x in (labels,boxes,scores)):
        raise ValueError('Non-finite detection output')
    if (labels<0).any() or (labels>=6).any() or (labels!=labels.astype(np.int64)).any():
        raise ValueError('Unexpected detection class index')
    if (scores<0).any() or (scores>1).any():
        raise ValueError('Invalid confidence probability')
    width,height=image.size
    results=[]
    for index in np.argsort(-scores[0],kind='stable'):
        score=float(scores[0,index])
        if score<=threshold:
            continue
        label=int(labels[0,index]);x0,y0,x1,y1=map(float,boxes[0,index])
        x0,x1=sorted((max(0.,min(width,x0)),max(0.,min(width,x1))))
        y0,y1=sorted((max(0.,min(height,y0)),max(0.,min(height,y1))))
        if x1<=x0 or y1<=y0:
            continue
        name=NAMES[label]
        results.append({'label':name,'score':score,'box':[x0,y0,x1,y1]})
    return render_detections(image, results), results
