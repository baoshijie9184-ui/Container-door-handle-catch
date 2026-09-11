"""
检测引擎模块 (detection_engine.py)
包含 DEIM 模型加载、推理和标注功能
供远程 Kafka worker 使用
"""

# --- 核心导入 ---
import torch
import torch.nn as nn
import torchvision.transforms as T
import numpy as np
from PIL import Image
import cv2
import os
import sys
import io
import math
from typing import List, Dict

# --- 引擎和配置导入 ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from engine.core import YAMLConfig

# --- 绘图工具导入 ---
try:
    from plotting import Annotator, Colors, is_ascii
    colors = Colors()
except ImportError:
    print("=" * 50)
    print("严重错误: 无法导入 'plotting.py'。")
    print("请确保 'plotting.py' 文件与 'detection_engine.py' 在同一个文件夹中。")
    print("=" * 50)
    sys.exit(1)

# --- 全局变量 ---
model = None
device = "cuda" if torch.cuda.is_available() else "cpu"

transforms = T.Compose([
    T.Resize((640, 640)),
    T.ToTensor(),
])

CONFIG_PATH = os.environ.get(
    "DEIM_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "configs", "deim_dfine", "dfine_hgnetv2_n_coco.yml"),
)
RESUME_PATH = os.environ.get(
    "DEIM_RESUME_PATH",
    os.path.join(os.path.dirname(__file__), "deim_outputs", "deim_hgnetv2_n_coco", "best_stg2.pth"),
)

NAMES = {
    0: 'Normal',
    1: 'Bent',
    2: 'Deformed',
    3: 'Rusty',
    4: 'Missing',
    5: 'Compromised',
}

OVERLAP_THRESHOLD_PX = 30


class InferenceModel(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.model = cfg.model.deploy()
        self.postprocessor = cfg.postprocessor.deploy()

    def forward(self, images, orig_target_sizes):
        outputs = self.model(images)
        outputs = self.postprocessor(outputs, orig_target_sizes)
        return outputs


def load_model():
    """加载 DEIM 模型（启动时调用一次）"""
    global model
    if model is None:
        print(f"正在加载模型... (设备: {device})")
        try:
            cfg = YAMLConfig(CONFIG_PATH, resume=RESUME_PATH)
            if 'HGNetv2' in cfg.yaml_cfg:
                cfg.yaml_cfg['HGNetv2']['pretrained'] = False
            checkpoint = torch.load(RESUME_PATH, map_location=device)
            state = checkpoint.get('ema', {}).get('module', checkpoint.get('model'))
            cfg.model.load_state_dict(state)
            model = InferenceModel(cfg).to(device)
            model.eval()
            print(f"模型已成功加载到 {device}")
        except FileNotFoundError:
            print(f"错误: 找不到模型文件或配置文件。")
            print(f"  Config path: {CONFIG_PATH}")
            print(f"  Resume path: {RESUME_PATH}")
            raise
        except Exception as e:
            print(f"模型加载失败: {e}")
            raise e


def ensure_model_loaded():
    """为 Kafka worker 提供统一的模型加载入口"""
    if model is None:
        load_model()
    return model


def get_annotated_image_and_json(im_pil, labels, boxes, scores, thrh=0.4):
    """使用 cv2 和 plotting.py 绘制标注，返回 (annotated_pil_image, json_results)"""
    im = cv2.cvtColor(np.array(im_pil), cv2.COLOR_RGB2BGR)
    lw = max(round(sum(im.shape) / 2 * 0.003), 2)
    annotator = Annotator(im, line_width=lw, example=str(NAMES))

    scr = scores[0].cpu()
    lab = labels[0].cpu()
    box = boxes[0].cpu()

    mask = scr > thrh
    lab = lab[mask]
    box = box[mask]
    scr = scr[mask]

    detections = list(zip(scr, lab, box))
    sorted_detections = sorted(detections, key=lambda x: x[0], reverse=True)
    drawn_labels_info = []
    results_json = []

    for score_tensor, class_id_tensor, box_tensor in sorted_detections:
        box_coords = [int(c) for c in box_tensor]
        class_id = int(class_id_tensor)
        score = float(score_tensor)

        x0, y0, x1, y1 = box_coords
        box_coords = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

        class_name = NAMES.get(class_id, f'Class {class_id}')
        label_text = f"{class_name} {score:.2f}"
        color = colors(class_id, bgr=True)

        current_label_anchor = (box_coords[0], box_coords[1])
        current_label_height = 0
        if annotator.pil or not is_ascii(label_text):
            try:
                w_text, h_text = annotator.font.getsize(label_text)
            except AttributeError:
                (w_text, h_text), _ = cv2.getTextSize(label_text, 0, fontScale=annotator.sf, thickness=annotator.tf)
            current_label_height = h_text + 1 + 1
        else:
            (w_text, h_text), _ = cv2.getTextSize(label_text, 0, fontScale=annotator.sf, thickness=annotator.tf)
            current_label_height = h_text + 3 + 1

        y_offset_pixels = 0
        for drawn_anchor_x, drawn_anchor_y, prev_label_h in drawn_labels_info:
            dist = math.dist(current_label_anchor, (drawn_anchor_x, drawn_anchor_y))
            if dist < OVERLAP_THRESHOLD_PX:
                y_offset_pixels += (prev_label_h + 2)

        drawn_labels_info.append((*current_label_anchor, current_label_height))

        try:
            annotator.box_label(box_coords, label_text, color=color, y_offset_pixels=y_offset_pixels)
        except TypeError:
            print("警告: 'Annotator.box_label' 不支持 'y_offset_pixels'。将不使用重叠避免。")
            annotator.box_label(box_coords, label_text, color=color)
        except Exception as e:
            print(f"Annotator 绘图时出错: {e}")

        results_json.append({
            "label": class_name,
            "score": score,
            "box": [float(c) for c in box_coords]
        })

    result_im_cv2 = annotator.result()
    annotated_pil_image = Image.fromarray(cv2.cvtColor(result_im_cv2, cv2.COLOR_BGR2RGB))
    return annotated_pil_image, results_json


def run_detection_on_pil_image(im_pil: Image.Image, threshold: float = 0.4):
    """从 PIL 图片执行检测，返回 (annotated_pil_image, detections_json)"""
    ensure_model_loaded()
    working_image = im_pil.convert('RGB')
    w, h = working_image.size
    orig_size = torch.tensor([[w, h]]).to(device)
    im_data = transforms(working_image).unsqueeze(0).to(device)

    with torch.no_grad():
        output = model(im_data, orig_size)
    labels, boxes, scores = output

    return get_annotated_image_and_json(
        working_image.copy(), labels, boxes, scores, thrh=threshold
    )


def run_detection_on_image_bytes(image_bytes: bytes, threshold: float = 0.4):
    """从二进制图片内容执行检测，供 Kafka worker 下载 OSS 原图后直接复用"""
    im_pil = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    return run_detection_on_pil_image(im_pil, threshold)
