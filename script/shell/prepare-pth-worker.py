"""Prepare an isolated worker build context from the user-provided, verified training ZIP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
from zipfile import ZipFile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-zip',type=Path,required=True)
    p.add_argument('--wheels',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('work/cloud/pth-worker-build'))
    p.add_argument('--archive',type=Path)
    args=p.parse_args();root=Path(__file__).resolve().parents[2]
    target=args.output.resolve();target.mkdir(parents=True,exist_ok=True)
    source=target/'model-source';source.mkdir(exist_ok=True)
    with ZipFile(args.source_zip) as z:
        for entry in z.infolist():
            relative=Path(entry.filename).relative_to('DEIMv2_WACGA')
            destination=(source/relative).resolve()
            if not destination.is_relative_to(source) or stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Unsafe training archive entry')
            if not entry.is_dir():
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(z.read(entry))
    hashes=json.loads((source/'MANIFEST_SHA256.json').read_text(encoding='utf-8'))
    if any(hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest for name,digest in hashes.items()):
        raise ValueError('Training source hashes do not match')
    files=['kafka_detection_worker.py','kafka_event_models.py','kafka_settings.py','detection_worker_receipts.py','oss_result_uploader.py',
           'pth_detection_engine.py','detection_image.py','worker_health.py','LICENSE']
    for name in files:shutil.copyfile(root/name,target/name)
    for name in ['Dockerfile','requirements.txt']:shutil.copyfile(root/'deploy/worker'/name,target/name)
    wheels=target/'cpu-wheels';wheels.mkdir(exist_ok=True)
    for wheel in args.wheels.glob('*.whl'):
        destination=wheels/wheel.name
        if not destination.exists():
            try:
                os.link(wheel.resolve(),destination)
            except OSError:
                shutil.copyfile(wheel,destination)
    provenance={'sourceZipSha256':hashlib.sha256(args.source_zip.read_bytes()).hexdigest(),
        'verifiedSourceFiles':len(hashes),'wheelSha256':{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in wheels.glob('*.whl')}}
    (target/'BUILD_PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    # Retain the existing DINOv3 terms alongside the supplied notices.
    dino_license=root/'deploy/worker/licenses/DINOv3-LICENSE.md'
    shutil.copyfile(dino_license,target/'DINOv3-LICENSE.md')
    shutil.copyfile(root/'deploy/worker/licenses/PyMySQL-LICENSE.txt',target/'PyMySQL-LICENSE.txt')
    deployment=target/'deployment';deployment.mkdir(exist_ok=True)
    shutil.copyfile(root/'deploy/worker/manifest.wacga.json',deployment/'manifest.json')
    shutil.copyfile(root/'compose.detection.yml',deployment/'compose.detection.yml')
    if args.archive:
        with tarfile.open(args.archive,'w:gz') as archive:
            for path in sorted(target.iterdir()):archive.add(path,arcname=path.name)
    print(json.dumps(provenance,indent=2))


if __name__=='__main__':main()
