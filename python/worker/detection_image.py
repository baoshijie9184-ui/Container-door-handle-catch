"""Shared image validation and annotation for native PyTorch inference."""
import math
import numpy as np
from PIL import ImageDraw

NAMES = ['Normal','Bent','Deformed','Rusty','Missing','Compromised']


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
    image=image.copy();draw=ImageDraw.Draw(image);width,height=image.size
    colors=['#1677ff','#d97706','#e85d04','#9a6324','#dc2626','#7c3aed'];results=[]
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
        draw.rectangle((x0,y0,x1,y1),outline=colors[label],width=max(2,round((width+height)/600)))
        draw.text((x0,max(0,y0-13)),f'{name} {score:.2f}',fill=colors[label])
        results.append({'label':name,'score':score,'box':[x0,y0,x1,y1]})
    return image,results
