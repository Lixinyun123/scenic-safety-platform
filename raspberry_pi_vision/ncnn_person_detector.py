"""Fast person-only NCNN inference for Raspberry Pi."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import ncnn
import numpy as np


@dataclass(frozen=True)
class Detection:
    box: tuple[int, int, int, int]
    confidence: float


def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[current], x1[rest])
        yy1 = np.maximum(y1[current], y1[rest])
        xx2 = np.minimum(x2[current], x2[rest])
        yy2 = np.minimum(y2[current], y2[rest])
        intersection = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[current] + areas[rest] - intersection
        iou = intersection / np.maximum(union, 1e-6)
        order = rest[iou <= threshold]
    return keep


class NCNNPersonDetector:
    """Runs the exported YOLO NCNN model without the generic PyTorch predictor stack."""

    def __init__(self, model_dir: str, input_width: int, input_height: int, threads: int = 4) -> None:
        model_path = Path(model_dir)
        param_path = model_path / "model.ncnn.param"
        bin_path = model_path / "model.ncnn.bin"
        if not param_path.is_file() or not bin_path.is_file():
            raise FileNotFoundError(f"NCNN model is incomplete: {model_path}")

        self.input_width = input_width
        self.input_height = input_height
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = threads
        self.net.load_param(str(param_path))
        self.net.load_model(str(bin_path))
        self.input_name = self.net.input_names()[0]
        self.output_name = self.net.output_names()[0]

    def detect(self, frame: np.ndarray, confidence: float, iou: float) -> list[Detection]:
        original_height, original_width = frame.shape[:2]
        scale = min(self.input_width / original_width, self.input_height / original_height)
        resized_width = int(round(original_width * scale))
        resized_height = int(round(original_height * scale))
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

        horizontal_padding = (self.input_width - resized_width) / 2
        vertical_padding = (self.input_height - resized_height) / 2
        left = int(round(horizontal_padding - 0.1))
        right = int(round(horizontal_padding + 0.1))
        top = int(round(vertical_padding - 0.1))
        bottom = int(round(vertical_padding + 0.1))
        letterboxed = cv2.copyMakeBorder(
            resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
        )
        tensor = ncnn.Mat.from_pixels(
            letterboxed,
            ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            self.input_width,
            self.input_height,
        )
        tensor.substract_mean_normalize([], [1.0 / 255.0, 1.0 / 255.0, 1.0 / 255.0])

        with self.net.create_extractor() as extractor:
            extractor.input(self.input_name, tensor)
            status, output = extractor.extract(self.output_name)
        if status != 0:
            raise RuntimeError(f"NCNN inference failed: {status}")

        prediction = np.asarray(output)
        if prediction.ndim != 2:
            raise RuntimeError(f"Unexpected NCNN output shape: {prediction.shape}")
        if prediction.shape[0] > prediction.shape[1]:
            prediction = prediction.T
        scores = prediction[4]  # COCO class 0 = person; rows 0..3 are xywh.
        candidates = np.flatnonzero(scores >= confidence)
        if candidates.size == 0:
            return []

        xywh = prediction[:4, candidates].T
        candidate_scores = scores[candidates]
        boxes = np.empty_like(xywh)
        boxes[:, 0] = xywh[:, 0] - xywh[:, 2] / 2
        boxes[:, 1] = xywh[:, 1] - xywh[:, 3] / 2
        boxes[:, 2] = xywh[:, 0] + xywh[:, 2] / 2
        boxes[:, 3] = xywh[:, 1] + xywh[:, 3] / 2

        detections: list[Detection] = []
        for index in _nms(boxes, candidate_scores, iou):
            x1 = int(np.clip((boxes[index, 0] - left) / scale, 0, original_width - 1))
            y1 = int(np.clip((boxes[index, 1] - top) / scale, 0, original_height - 1))
            x2 = int(np.clip((boxes[index, 2] - left) / scale, 0, original_width - 1))
            y2 = int(np.clip((boxes[index, 3] - top) / scale, 0, original_height - 1))
            if x2 > x1 and y2 > y1:
                detections.append(Detection((x1, y1, x2, y2), float(candidate_scores[index])))
        return detections


def draw_detections(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
    annotated = frame.copy()
    for detection in detections:
        x1, y1, x2, y2 = detection.box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"person {detection.confidence:.2f}"
        cv2.putText(
            annotated,
            label,
            (x1, max(20, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    return annotated
