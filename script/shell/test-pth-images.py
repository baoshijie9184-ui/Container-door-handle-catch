"""Run a reproducible image sample through the exact native PyTorch worker engine."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import Image
from pth_detection_engine import PthDetectionEngine,sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--samples',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--threshold',type=float,default=.5)
    args=p.parse_args()
    sample=json.loads(args.samples.read_text(encoding='utf-8'))
    root=Path(sample['root']).resolve();paths=[(root/name).resolve() for name in sample['images']]
    if not all(path.is_relative_to(root) for path in paths):
        raise ValueError('Sample path outside the selected directory')
    args.output.mkdir(parents=True,exist_ok=True)
    model=PthDetectionEngine(args.manifest,args.source)
    rows=[];errors=[]
    for index,path in enumerate(paths,1):
        try:
            with Image.open(path) as image:
                annotated,detections=model.predict(image,args.threshold)
            rows.append({'image':str(path),'imageSha256':sha256(path),'size':annotated.size,
                'torchMs':round(model.last_inference_ms,3),'threshold':args.threshold,
                'detections':detections,'passed':True})
        except Exception as error:
            errors.append({'image':str(path),'error':str(error)})
        if index%10==0 or index==len(paths):
            (args.output/'partial-results.json').write_text(json.dumps({'images':rows,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
            print(f'PTH tested {index}/{len(paths)}, failures={len(errors)}',flush=True)
    with Image.open(paths[0]) as image:
        _,repeated=model.predict(image,args.threshold)
    repeatable=not errors and repeated==rows[0]['detections']
    report={'kind':'NATIVE_PYTORCH_PTH_INFERENCE','format':'pth','apEvaluated':False,
        'imageCount':len(paths),'threshold':args.threshold,'cpuThreads':2,'seed':sample.get('seed'),
        'loadReport':model.load_report,'repeatabilityPassed':repeatable,
        'images':rows,'errors':errors,'passed':not errors and repeatable}
    (args.output/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['images','errors']},ensure_ascii=True))
    if not report['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
