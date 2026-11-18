"""Load the supplied WACGA PTH checkpoint directly, with its exact training source."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageOps
from detection_image import NAMES, annotate


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


class PthDetectionEngine:
    def __init__(self,manifest_path,source_dir=None):
        manifest_path=Path(manifest_path).resolve()
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('schemaVersion')!=1 or manifest.get('format')!='pth' or manifest.get('classNames')!=NAMES:
            raise ValueError('Unexpected PTH model manifest')
        source=Path(source_dir or os.environ['DETECTION_SOURCE_DIR']).resolve()
        hashes=json.loads((source/'MANIFEST_SHA256.json').read_text(encoding='utf-8'))
        for name,digest in hashes.items():
            path=(source/name).resolve()
            if not path.is_relative_to(source) or sha256(path)!=digest:
                raise ValueError('Training source checksum mismatch: '+name)
        metadata=json.loads((source/'CHECKPOINT_METADATA.json').read_text(encoding='utf-8'))
        checkpoint=(manifest_path.parent/manifest['modelFile']).resolve()
        if not checkpoint.is_relative_to(manifest_path.parent):
            raise ValueError('Checkpoint must be in the manifest directory')
        self.sha256=sha256(checkpoint)
        if self.sha256!=manifest['checkpointSha256'] or self.sha256!=metadata['checkpoint_sha256']:
            raise ValueError('Checkpoint SHA-256 mismatch')
        config=source/'configs/portable/wacga_shrinkage_s3_inference.yml'
        if sha256(config)!=manifest['configSha256']:
            raise ValueError('Inference config SHA-256 mismatch')
        sys.path.insert(0,str(source))
        import torch
        from torchvision import transforms as T
        from engine.core import YAMLConfig
        from engine.deim.wacga_shrinkage import HybridEncoderWACGAShrinkage
        self.torch=torch
        torch.set_num_threads(int(os.getenv('DETECTION_CPU_THREADS','2')))
        cfg=YAMLConfig(str(config))
        if cfg.yaml_cfg['PostProcessor']['category_ids']!=[1,2,3,4,5,6]:
            raise ValueError('Unexpected source class mapping')
        loaded=torch.load(checkpoint,map_location='cpu',weights_only=True)
        self.model=cfg.model.cpu().eval()
        if not isinstance(self.model.encoder,HybridEncoderWACGAShrinkage):
            raise ValueError('Expected the supplied WACGA shrinkage architecture')
        state=loaded['ema']['module']
        result=self.model.load_state_dict(state,strict=True)
        self.load_report={'strictLoad':True,'missingKeys':list(result.missing_keys),
            'unexpectedKeys':list(result.unexpected_keys),'stateTensors':len(state),'checkpointState':'ema',
            'checkpointRound':int(loaded['last_epoch'])+1,'checkpointSha256':self.sha256,
            'torchVersion':torch.__version__,'format':'pth','sourceFilesVerified':len(hashes)}
        self.postprocessor=cfg.postprocessor.cpu().eval().deploy()
        # Preserve the original trained model; no deploy fusion or format conversion.
        self.transform=T.Compose([T.Resize((640,640)),T.ToTensor(),T.Normalize([.485,.456,.406],[.229,.224,.225])])
        self.last_inference_ms=None
        self.predict(Image.new('RGB',(640,640)),1.0)

    def predict(self,image,threshold=.5):
        if not math.isfinite(threshold) or not 0<=threshold<=1:
            raise ValueError('Detection threshold must be between zero and one')
        image=ImageOps.exif_transpose(image).convert('RGB')
        if image.width*image.height>40_000_000:
            raise ValueError('Image exceeds inference pixel limit')
        tensor=self.transform(image)[None]
        size=self.torch.tensor([image.size],dtype=self.torch.int64)
        started=time.perf_counter()
        with self.torch.inference_mode():
            raw=self.model(tensor)
            if raw['pred_logits'].shape!=(1,300,6) or raw['pred_boxes'].shape!=(1,300,4):
                raise ValueError('Malformed raw detection tensors')
            if not all(self.torch.isfinite(raw[k]).all() for k in ['pred_logits','pred_boxes']):
                raise ValueError('Non-finite raw model output')
            labels,boxes,scores=self.postprocessor(raw,size)
        self.last_inference_ms=(time.perf_counter()-started)*1000
        return annotate(image,labels.cpu().numpy()-1,boxes.cpu().numpy(),scores.cpu().numpy(),threshold)

    def detect_bytes(self,content,threshold=.5):
        with Image.open(io.BytesIO(content)) as image:
            return self.predict(image,threshold)


_engine=None


def ensure_model_loaded():
    global _engine
    if _engine is None:
        _engine=PthDetectionEngine(os.environ['DETECTION_MODEL_MANIFEST'])
    return _engine


def run_detection_on_image_bytes(content,threshold=.5):
    return ensure_model_loaded().detect_bytes(content,threshold)
