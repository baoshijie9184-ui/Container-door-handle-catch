"""Render a second copy of a finished local folder task's labels from its original model boxes."""
import argparse
import io
import json
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps
from detection_image import render_detections
from kafka_detection_worker import create_oss_bucket, folder_source_bucket, load_settings


def refresh(task_id, dispatch_id):
    if not re.fullmatch(r'det_folder_[0-9a-f]{32}', task_id) or not re.fullmatch(r'[0-9a-f-]{36}', dispatch_id):
        raise ValueError('Invalid folder task or dispatch')
    directory = Path(os.environ['FOLDER_RESULTS_DIR']) / task_id / dispatch_id
    report = json.loads((directory / 'detection_results.json').read_text())
    if report.get('taskId') != task_id or not isinstance(report.get('results'), list):
        raise ValueError('Result manifest belongs to another task or has no detections list')
    dest = directory / '.annotations-song-v1'
    dest.mkdir(exist_ok=True)
    bucket = folder_source_bucket(create_oss_bucket(load_settings()))
    for item in report['results']:
        name = item['fileName']
        if not name or '/' in name or chr(92) in name or not name.lower().endswith(('.jpg','.jpeg','.png','.bmp')):
            raise ValueError('Invalid image name in model result')
        if item['previewKey'] != f'detection/folder-results/{task_id}/{dispatch_id}/{name}':
            raise ValueError('Preview does not belong to this dispatch')
        key = item['sourceKey']
        if not key.startswith('detection/') or not key.endswith('/'+name) or not (directory/name).is_file():
            raise ValueError('Original and annotated image pair could not be verified')
        raw = bucket.get_object(key).read(26_214_401)
        if len(raw) > 26_214_400:
            raise ValueError('Original exceeds input limit')
        with Image.open(io.BytesIO(raw)) as original:
            if original.width * original.height > 40_000_000:
                raise ValueError('Original exceeds pixel limit')
            rendered = render_detections(ImageOps.exif_transpose(original), item['detections'])
        with tempfile.NamedTemporaryFile(dir=dest,delete=False) as tmp:
            try:
                rendered.save(tmp,format='JPEG',quality=92,subsampling=0)
                tmp.flush()
                os.replace(tmp.name,dest/name)
            finally:
                Path(tmp.name).unlink(missing_ok=True)
    print(f'{task_id}: {len(report["results"])} rendered')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_id')
    parser.add_argument('dispatch_id')
    args = parser.parse_args()
    refresh(args.task_id,args.dispatch_id)
