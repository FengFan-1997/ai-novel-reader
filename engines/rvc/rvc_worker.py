"""Long-lived JSONL worker for narrator-only RVC conversion.

This file intentionally lives outside the main environment.  It is launched by
``src.rvc_service`` with the Python executable from ``data/rvc/venv`` so RVC's
older Torch/Numpy requirements cannot destabilize the audiobook application.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import traceback


def _send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--index", default="")
    parser.add_argument("--device", default="cpu:0")
    parser.add_argument("--pitch-method", default="rmvpe")
    parser.add_argument("--f0up-key", type=int, default=0)
    parser.add_argument("--index-rate", type=float, default=0.5)
    parser.add_argument("--filter-radius", type=int, default=3)
    parser.add_argument("--rms-mix-rate", type=float, default=1.0)
    parser.add_argument("--protect", type=float, default=0.33)
    args = parser.parse_args()

    try:
        # Some RVC modules print model diagnostics. Keep stdout reserved for JSON.
        with contextlib.redirect_stdout(sys.stderr):
            import torch

            # rvc-python 0.1.5 always overrides an explicit CPU request with
            # MPS when Metal exists. Its fairseq inference path can segfault on
            # current macOS Torch builds, so honour this worker's CPU setting.
            if str(args.device).lower().startswith("cpu"):
                torch.backends.mps.is_available = lambda: False

            # fairseq checkpoints predate PyTorch 2.6's weights_only=True
            # default. This worker loads only the explicitly configured local
            # RVC/base-model files, so retain the legacy loader inside this
            # isolated process without weakening the main application runtime.
            original_torch_load = torch.load

            def compatible_torch_load(*load_args, **load_kwargs):
                load_kwargs.setdefault("weights_only", False)
                return original_torch_load(*load_args, **load_kwargs)

            torch.load = compatible_torch_load
            from rvc_python.infer import RVCInference

            converter = RVCInference(
                device=args.device,
                model_path=args.model,
                index_path=args.index,
                version="v2",
            )
            converter.set_params(
                f0method=args.pitch_method,
                index_rate=args.index_rate,
                f0up_key=args.f0up_key,
                filter_radius=args.filter_radius,
                protect=args.protect,
                rms_mix_rate=args.rms_mix_rate,
            )
        _send({"ready": True})
    except Exception as exc:
        _send({"ready": False, "error": str(exc)})
        traceback.print_exc(file=sys.stderr)
        return 1

    for raw_line in sys.stdin:
        try:
            message = json.loads(raw_line)
            if message.get("command") == "shutdown":
                _send({"ok": True})
                break
            if message.get("command") != "convert":
                raise ValueError("Unsupported command")
            with contextlib.redirect_stdout(sys.stderr):
                converter.infer_file(message["input"], message["output"])
            _send({"ok": True, "output": message["output"]})
        except Exception as exc:
            _send({"ok": False, "error": str(exc)})
            traceback.print_exc(file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
