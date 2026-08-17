"""Compare direct NCNN CPU and Vulkan inference without camera overhead."""

from __future__ import annotations

import argparse
import time

import ncnn
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolo26n_640_ncnn_model")
    parser.add_argument("--size", type=int, default=640)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--vulkan", action="store_true")
    parser.add_argument("--fp16", action="store_true")
    args = parser.parse_args()

    net = ncnn.Net()
    net.opt.use_vulkan_compute = args.vulkan
    net.opt.num_threads = args.threads
    net.opt.use_fp16_packed = args.fp16
    net.opt.use_fp16_storage = args.fp16
    net.opt.use_fp16_arithmetic = args.fp16
    net.load_param(f"{args.model}/model.ncnn.param")
    net.load_model(f"{args.model}/model.ncnn.bin")
    sample = np.random.random((3, args.size, args.size)).astype(np.float32)

    durations = []
    for index in range(args.runs + 3):
        started = time.perf_counter()
        with net.create_extractor() as extractor:
            extractor.input("in0", ncnn.Mat(sample))
            status, output = extractor.extract("out0")
        if status != 0:
            raise RuntimeError(f"NCNN extraction failed: {status}")
        if index >= 3:
            durations.append(time.perf_counter() - started)

    average = sum(durations) / len(durations)
    print(
        f"backend={'vulkan' if args.vulkan else 'cpu'} threads={args.threads} fp16={args.fp16} "
        f"shape={np.array(output).shape} average_ms={average * 1000:.1f} fps={1 / average:.1f}"
    )


if __name__ == "__main__":
    main()
