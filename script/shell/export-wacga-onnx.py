"""Export the provided WACGA checkpoint only after strict load and numerical parity."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from detection_parity import compare_detections, compare_raw


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--weights',type=Path,required=True)
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--images',type=Path,nargs='+')
    selection.add_argument('--samples',type=Path,help='JSON with root and relative images, e.g. a reproducible 100-image sample')
    parser.add_argument('--threshold',type=float,default=.5)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 0<=args.threshold<=1:
        parser.error('threshold must be between zero and one')
    if args.samples:
        selection=json.loads(args.samples.read_text(encoding='utf-8'))
        image_root=Path(selection['root']).resolve()
        args.images=[(image_root/name).resolve() for name in selection['images']]
        if not args.images or not all(path.is_relative_to(image_root) for path in args.images):
            raise ValueError('Sample paths must be inside the image root')
    source=args.source.resolve()
    hashes=json.loads((source/'MANIFEST_SHA256.json').read_text(encoding='utf-8'))
    for name,digest in hashes.items():
        path=(source/name).resolve()
        if not path.is_relative_to(source) or sha256(path)!=digest:
            raise ValueError('Training source checksum mismatch: '+name)
    metadata=json.loads((source/'CHECKPOINT_METADATA.json').read_text(encoding='utf-8'))
    checkpoint_digest=sha256(args.weights)
    if checkpoint_digest!=metadata['checkpoint_sha256']:
        raise ValueError('Checkpoint does not match packaged training metadata')
    sys.path.insert(0,str(source))
    import torch
    import numpy as np
    import onnx
    import onnxruntime as ort
    from PIL import Image,ImageOps
    from torchvision import transforms as T
    from engine.core import YAMLConfig
    from engine.deim.wacga_shrinkage import HybridEncoderWACGAShrinkage

    torch.set_num_threads(2)
    config=source/'configs/portable/wacga_shrinkage_s3_inference.yml'
    cfg=YAMLConfig(str(config))
    if cfg.yaml_cfg['PostProcessor']['category_ids']!=[1,2,3,4,5,6]:
        raise ValueError('Recheck source dataset category mapping')
    checkpoint=torch.load(args.weights,map_location='cpu',weights_only=True)
    loaded=cfg.model.load_state_dict(checkpoint['ema']['module'],strict=True)
    if not isinstance(cfg.model.encoder,HybridEncoderWACGAShrinkage):
        raise ValueError('Unexpected model encoder')
    original=cfg.model.eval()
    post=cfg.postprocessor.eval().deploy()

    class ExportModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.network=copy.deepcopy(original).deploy()
            self.post=copy.deepcopy(post)
        def forward(self,images,orig_target_sizes):
            outputs=self.network(images)
            labels,boxes,scores=self.post(outputs,orig_target_sizes)
            # Dataset IDs 1..6 become model indices 0..5; names are business aliases.
            return labels-1,boxes,scores,outputs['pred_logits'],outputs['pred_boxes']

    preprocess=T.Compose([T.Resize((640,640)),T.ToTensor(),T.Normalize([.485,.456,.406],[.229,.224,.225])])
    first=ImageOps.exif_transpose(Image.open(args.images[0])).convert('RGB')
    inputs=(preprocess(first)[None],torch.tensor([first.size],dtype=torch.int64))
    with torch.no_grad():
        raw=original(inputs[0])
        labels,boxes,scores=post(raw,inputs[1])
        before=[labels.numpy()-1,boxes.numpy(),scores.numpy()]
        model=ExportModel().eval()
        after=[x.numpy() for x in model(*inputs)]
        compare_raw([raw['pred_logits'].numpy(),raw['pred_boxes'].numpy()],after[3:])
        compare_detections(before,after[:3],args.threshold)
    args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/'model.onnx'
    manifest_path=args.output/'manifest.json'
    if target.exists() or manifest_path.exists():
        raise FileExistsError('Use a fresh output directory; validated artifacts are not overwritten')
    torch.onnx.export(model,inputs,str(target),input_names=['images','orig_target_sizes'],
        output_names=['labels','boxes','scores','pred_logits','pred_boxes'],opset_version=17,do_constant_folding=True)
    onnx.checker.check_model(onnx.load(target))
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(target),sess_options=options,providers=['CPUExecutionProvider'])
    parity=[]
    names=['Normal','Bent','Deformed','Rusty','Missing','Compromised']
    for number,image_path in enumerate(args.images,1):
        image=ImageOps.exif_transpose(Image.open(image_path)).convert('RGB')
        tensors=(preprocess(image)[None],torch.tensor([image.size],dtype=torch.int64))
        started=time.perf_counter()
        with torch.no_grad():
            raw=original(tensors[0])
            labels,boxes,scores=post(raw,tensors[1])
            reference=[labels.numpy()-1,boxes.numpy(),scores.numpy()]
        torch_ms=(time.perf_counter()-started)*1000
        started=time.perf_counter()
        actual=session.run(['labels','boxes','scores','pred_logits','pred_boxes'],{'images':tensors[0].numpy(),'orig_target_sizes':tensors[1].numpy()})
        onnx_ms=(time.perf_counter()-started)*1000
        raw_parity=compare_raw([raw['pred_logits'].numpy(),raw['pred_boxes'].numpy()],actual[3:])
        visible_parity=compare_detections(reference,actual[:3],args.threshold)
        detections=[]
        for label,box,score in zip(actual[0][0],actual[1][0],actual[2][0]):
            if score>args.threshold:
                x0,y0,x1,y1=map(float,box)
                width,height=image.size
                x0,x1=sorted((max(0.,min(width,x0)),max(0.,min(width,x1))))
                y0,y1=sorted((max(0.,min(height,y0)),max(0.,min(height,y1))))
                if x1>x0 and y1>y0:
                    detections.append({'label':names[int(label)],'score':float(score),'box':[x0,y0,x1,y1]})
        parity.append({'image':str(image_path),'imageSha256':sha256(image_path),'size':image.size,
            'torchMs':round(torch_ms,3),'onnxMs':round(onnx_ms,3),'threshold':args.threshold,
            **raw_parity,**visible_parity,'detections':detections})
        if number%10==0 or number==len(args.images):
            print(f'Validated {number}/{len(args.images)} images',flush=True)
    # Validation outputs expose all raw model tensors; production contract has only three outputs.
    exported=onnx.load(target)
    del exported.graph.output[3:]
    onnx.checker.check_model(exported)
    onnx.save(exported,target)
    validation={'kind':'FP32_EXPORT_PARITY_AND_INFERENCE','apEvaluated':False,
        'imageCount':len(parity),'threshold':args.threshold,'cpuThreads':2,
        'reference':'Original EMA PyTorch model before deploy fusion',
        'rawAllQueriesChecked':True,'topKOrderIsNotASemanticGate':True,
        'images':parity,'passed':True}
    (args.output/'validation-report.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'schemaVersion':1,'modelFile':target.name,'onnxSha256':sha256(target),
        'checkpointSha256':checkpoint_digest,'checkpointState':'ema','sourceConfigSha256':sha256(config),
        'classNames':['Normal','Bent','Deformed','Rusty','Missing','Compromised'],
        'sourceCategoryIds':[1,2,3,4,5,6],
        'sourceCategoryNames':['Normal','Bend','Deformation','Rusty','Missing','Compromised'],
        'inputSize':[640,640],'mean':[.485,.456,.406],'std':[.229,.224,.225],
        'encoder':'HybridEncoderWACGAShrinkage','torchVersion':torch.__version__,
        'onnxruntimeVersion':ort.__version__,'strictLoad':not loaded.missing_keys and not loaded.unexpected_keys,
        'parity':{'imageCount':len(parity),'threshold':args.threshold,'passed':True,
            'logitsMaxAbsError':max(p['logitsMaxAbsError'] for p in parity),
            'normalizedBoxesMaxAbsError':max(p['normalizedBoxesMaxAbsError'] for p in parity),
            'boxMaxAbsErrorPixels':max(p['boxMaxAbsErrorPixels'] for p in parity),
            'scoreMaxAbsError':max(p['scoreMaxAbsError'] for p in parity)},'apEvaluated':False}
    # Keep all supplied third-party notices with the privately deployed model.
    licenses=args.output/'licenses';licenses.mkdir()
    for path in source.rglob('*'):
        if path.is_file() and ('license' in path.name.lower() or 'notice' in path.name.lower()):
            destination=licenses/path.relative_to(source)
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
