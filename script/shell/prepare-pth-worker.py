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


PORTABLE_SOURCE_SHA256 = '19d74a8cb1cfdf542869cbaba0c229888015317122855807351be777fba61abc'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def add_fourband_config(source, config, manifest, hashes):
    metadata = {
        'checkpoint_sha256': manifest['checkpointSha256'],
        'encoder_class': manifest['encoder'],
        'best_val_round': 40,
        'training_config': 'configs/detection/components_v5_fixed640_68e_20261029/02_fourband_v1.yml',
    }
    config_relative = 'configs/portable/fourband_v1_inference.yml'
    metadata_name = 'CHECKPOINT_METADATA.fourband-v1.json'
    shutil.copyfile(config, source / config_relative)
    (source / metadata_name).write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    hashes[config_relative] = sha256(source / config_relative)
    hashes[metadata_name] = sha256(source / metadata_name)
    (source / 'MANIFEST_SHA256.json').write_text(json.dumps(hashes, indent=2) + '\n', encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-zip',type=Path,required=True)
    p.add_argument('--wheels',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('work/cloud/pth-worker-build'))
    p.add_argument('--archive',type=Path)
    p.add_argument('--fourband-checkpoint', type=Path,
                   help='Verify the selected v5 four-band checkpoint and prepare its worker in a new output directory')
    args=p.parse_args();root=Path(__file__).resolve().parents[2]
    worker_dir = root / 'deploy/worker'
    source_digest = sha256(args.source_zip)
    manifest_path = worker_dir / 'manifest.wacga.json'
    if args.fourband_checkpoint is not None:
        manifest_path = worker_dir / 'manifest.fourband-v1.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        config = worker_dir / 'fourband_v1_inference.yml'
        if source_digest != PORTABLE_SOURCE_SHA256 or sha256(config) != manifest['configSha256']:
            raise ValueError('Four-band worker source or inference config checksum mismatch')
        if sha256(args.fourband_checkpoint) != manifest['checkpointSha256']:
            raise ValueError('Four-band checkpoint checksum mismatch')
    target = args.output.resolve()
    if args.fourband_checkpoint is not None:
        target.mkdir(parents=True, mode=0o700)
        # The build copies files as root and runs as app. Keep the host context
        # private while giving the copied source and scripts normal read access.
        os.umask(0o022)
    else:
        target.mkdir(parents=True, exist_ok=True)
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
    for name, digest in hashes.items():
        path = (source / name).resolve()
        if not path.is_relative_to(source) or sha256(path) != digest:
            raise ValueError('Training source checksum mismatch: ' + name)
    if args.fourband_checkpoint is not None:
        add_fourband_config(source, config, manifest, hashes)
    files=['kafka_detection_worker.py','kafka_event_models.py','kafka_settings.py','detection_worker_receipts.py','oss_result_uploader.py',
           'pth_detection_engine.py','detection_image.py','worker_health.py','tenant_detection_authority.py','tenant_execution_security.py']
    (target/'fonts').mkdir(exist_ok=True)
    for name in ('annotation-song.otf','OFL.txt'):
        shutil.copyfile(root/'python/worker/fonts'/name,target/'fonts'/name)
    for name in files:shutil.copyfile(root/'python/worker'/name,target/name)
    shutil.copyfile(root/'python/shared/runtime_telemetry.py',target/'runtime_telemetry.py')
    shutil.copyfile(root/'LICENSE',target/'LICENSE')
    for name in ['Dockerfile','requirements.txt']:shutil.copyfile(root/'deploy/worker'/name,target/name)
    wheels=target/'cpu-wheels';wheels.mkdir(exist_ok=True)
    for wheel in args.wheels.glob('*.whl'):
        destination=wheels/wheel.name
        if not destination.exists():
            try:
                os.link(wheel.resolve(),destination)
            except OSError:
                shutil.copyfile(wheel,destination)
    provenance={'sourceZipSha256':source_digest,
        'verifiedSourceFiles':len(hashes),'wheelSha256':{path.name:sha256(path) for path in wheels.glob('*.whl')}}
    (target/'BUILD_PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    # Retain the existing DINOv3 terms alongside the supplied notices.
    dino_license=root/'deploy/worker/licenses/DINOv3-LICENSE.md'
    shutil.copyfile(dino_license,target/'DINOv3-LICENSE.md')
    shutil.copyfile(root/'deploy/worker/licenses/PyMySQL-LICENSE.txt',target/'PyMySQL-LICENSE.txt')
    deployment=target/'deployment';deployment.mkdir(exist_ok=True)
    shutil.copyfile(manifest_path,deployment/'manifest.json')
    shutil.copyfile(root/'deploy/compose/compose.detection.yml',deployment/'compose.detection.yml')
    if args.archive:
        with tarfile.open(args.archive,'w:gz') as archive:
            for path in sorted(target.iterdir()):archive.add(path,arcname=path.name)
    print(json.dumps(provenance,indent=2))


if __name__=='__main__':main()
