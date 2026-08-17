"""Train the one-class person-in-water detector on the Windows RTX GPU."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
import yaml
from ultralytics import YOLO


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def verify_dataset(root: Path) -> None:
    counts: dict[str, tuple[int, int]] = {}
    for split in ("train", "val"):
        image_dir = root / "dataset" / "images" / split
        label_dir = root / "dataset" / "labels" / split
        images = [path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES]
        positive_labels = 0
        for image in images:
            label = label_dir / f"{image.stem}.txt"
            if not label.exists() or not label.read_text(encoding="utf-8").strip():
                continue  # Missing/empty label means a hard-negative background image.
            for line_number, line in enumerate(label.read_text(encoding="utf-8").splitlines(), 1):
                values = line.split()
                if len(values) != 5 or values[0] != "0":
                    raise ValueError(f"标签格式错误：{label}:{line_number}")
                coordinates = [float(value) for value in values[1:]]
                if any(value < 0 or value > 1 for value in coordinates):
                    raise ValueError(f"坐标不在0～1范围：{label}:{line_number}")
            positive_labels += 1
        counts[split] = (len(images), positive_labels)

    print(f"训练集：{counts['train'][0]} 张，其中正样本 {counts['train'][1]} 张")
    print(f"验证集：{counts['val'][0]} 张，其中正样本 {counts['val'][1]} 张")
    if counts["train"][1] < 100 or counts["val"][1] < 30:
        raise RuntimeError("正样本还太少：建议训练集至少100张、验证集至少30张后再试跑。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    verify_dataset(root)
    if not torch.cuda.is_available():
        raise RuntimeError("没有检测到CUDA显卡，请不要用CPU训练。")
    print(f"训练显卡：{torch.cuda.get_device_name(0)}")

    resolved_yaml = root / "dataset" / "data.resolved.yaml"
    resolved_yaml.write_text(
        yaml.safe_dump(
            {
                "path": str((root / "dataset").resolve()),
                "train": "images/train",
                "val": "images/val",
                "names": {0: "person_in_water"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    model = YOLO(args.model)
    model.train(
        data=str(resolved_yaml),
        epochs=args.epochs,
        patience=30,
        imgsz=args.imgsz,
        batch=args.batch,
        device=0,
        workers=args.workers,
        amp=True,
        cache=False,
        close_mosaic=10,
        cos_lr=True,
        seed=42,
        deterministic=True,
        project=str(root / "runs"),
        name="person_in_water",
        exist_ok=False,
        plots=True,
    )


if __name__ == "__main__":
    main()
