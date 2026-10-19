"""Persistent, optional narrator voice-conversion adapter."""
from __future__ import annotations

import atexit
import json
import logging
import os
import selectors
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


logger = logging.getLogger(__name__)


def project_conversion_seconds(samples: list[float], total_segments: int) -> float:
    """Project RVC-only work while treating the first load as a cold start."""
    clean = [max(0.0, float(value)) for value in samples if float(value) >= 0]
    total = max(0, int(total_segments))
    if len(clean) < 3 or total <= 0:
        return 0.0
    warm = sorted(clean[1:])
    midpoint = len(warm) // 2
    if len(warm) % 2:
        typical_warm = warm[midpoint]
    else:
        typical_warm = (warm[midpoint - 1] + warm[midpoint]) / 2
    return clean[0] + typical_warm * max(0, total - 1)


class RVCService:
    """Own one RVC subprocess and degrade cleanly when it is unavailable."""

    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self._process: Optional[subprocess.Popen] = None
        self._signature: Optional[Tuple[str, ...]] = None
        self._lock = threading.Lock()
        self._stderr_lock = threading.Lock()
        self._stderr_tail: list[str] = []
        self._stderr_thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None
        atexit.register(self.close)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _paths(self, config: Dict[str, Any]) -> Tuple[Path, Path, Path]:
        rvc_root = self.project_root / "data" / "rvc"
        model = Path(
            config.get("rvc_model_path")
            or rvc_root / "yae_miko" / "Yae_MikoJP.pth"
        )
        index = Path(
            config.get("rvc_index_path")
            or rvc_root / "yae_miko" / "Yae_MikoJP.index"
        )
        python_path = Path(
            config.get("rvc_python_path")
            or rvc_root / "venv" / "bin" / "python"
        )
        if not python_path.exists():
            python_path = Path(sys.executable)
        return model, index, python_path

    def status(self, config: Dict[str, Any]) -> Dict[str, Any]:
        model, index, python_path = self._paths(config)
        enabled = bool(config.get("rvc_enabled", True))
        return {
            "enabled": enabled,
            "available": bool(
                enabled and model.is_file() and index.is_file() and python_path.is_file()
            ),
            "running": bool(self._process and self._process.poll() is None),
            "model_path": str(model),
            "index_path": str(index),
            "python_path": str(python_path),
            "fallback": "fox_lady",
            "error": self._last_error,
        }

    def _drain_stderr(self, process: subprocess.Popen) -> None:
        """Keep verbose first-run downloads from filling the worker pipe."""
        if not process.stderr:
            return
        try:
            for line in iter(process.stderr.readline, ""):
                clean = line.rstrip()
                if not clean:
                    continue
                with self._stderr_lock:
                    self._stderr_tail.append(clean)
                    del self._stderr_tail[:-80]
                logger.debug("RVC worker: %s", clean)
        except Exception:
            return

    def _stderr_excerpt(self) -> str:
        with self._stderr_lock:
            return "\n".join(self._stderr_tail[-20:])[-2400:]

    def _read_json_line(self, timeout: float) -> Dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise RuntimeError("RVC worker is not running")
        selector = selectors.DefaultSelector()
        selector.register(self._process.stdout, selectors.EVENT_READ)
        try:
            events = selector.select(max(0.1, timeout))
            if not events:
                raise TimeoutError("RVC worker timed out")
            line = self._process.stdout.readline()
            if not line:
                stderr = self._stderr_excerpt()
                raise RuntimeError(f"RVC worker exited unexpectedly. {stderr}".strip())
            return json.loads(line)
        finally:
            selector.close()

    def _ensure_started(self, config: Dict[str, Any]) -> bool:
        model, index, python_path = self._paths(config)
        if not bool(config.get("rvc_enabled", True)):
            self._last_error = "八重声线增强已关闭"
            return False
        if not model.is_file() or not index.is_file():
            self._last_error = "八重声线模型尚未安装，已使用狐系御姐旁白"
            return False

        signature = (
            str(python_path),
            str(model),
            str(index),
            str(config.get("rvc_device") or "cpu:0"),
            str(config.get("rvc_pitch_method") or "rmvpe"),
            str(int(config.get("rvc_f0up_key") or 0)),
            str(config.get("rvc_index_rate") or 0.5),
            str(int(config.get("rvc_filter_radius") or 3)),
            str(config.get("rvc_rms_mix_rate") or 1.0),
            str(config.get("rvc_protect") or 0.33),
        )
        if (
            self._process
            and self._process.poll() is None
            and self._signature == signature
        ):
            return True
        self.close()

        worker_path = self.project_root / "engines" / "rvc" / "rvc_worker.py"
        command = [
            str(python_path),
            "-u",
            str(worker_path),
            "--model",
            str(model),
            "--index",
            str(index),
            "--device",
            str(config.get("rvc_device") or "cpu:0"),
            "--pitch-method",
            str(config.get("rvc_pitch_method") or "rmvpe"),
            "--f0up-key",
            str(int(config.get("rvc_f0up_key") or 0)),
            "--index-rate",
            str(float(config.get("rvc_index_rate") or 0.5)),
            "--filter-radius",
            str(int(config.get("rvc_filter_radius") or 3)),
            "--rms-mix-rate",
            str(float(config.get("rvc_rms_mix_rate") or 1.0)),
            "--protect",
            str(float(config.get("rvc_protect") or 0.33)),
        ]
        try:
            with self._stderr_lock:
                self._stderr_tail.clear()
            self._process = subprocess.Popen(
                command,
                cwd=str(self.project_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(self._process,),
                name="rvc-stderr",
                daemon=True,
            )
            self._stderr_thread.start()
            ready = self._read_json_line(float(config.get("rvc_start_timeout") or 120))
            if not ready.get("ready"):
                raise RuntimeError(ready.get("error") or "RVC worker failed to start")
            self._signature = signature
            self._last_error = None
            return True
        except Exception as exc:
            self._last_error = f"八重声线增强不可用：{exc}"
            logger.warning(self._last_error)
            self.close()
            return False

    def convert(
        self,
        input_path: Path | str,
        output_path: Path | str,
        config: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Convert one narrator segment.

        Returns ``(converted, warning)``.  Callers should retain the original
        fox-lady render whenever ``converted`` is false.
        """
        with self._lock:
            if not self._ensure_started(config):
                return False, self._last_error
            assert self._process and self._process.stdin
            try:
                self._process.stdin.write(
                    json.dumps(
                        {
                            "command": "convert",
                            "input": str(Path(input_path).resolve()),
                            "output": str(Path(output_path).resolve()),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                self._process.stdin.flush()
                result = self._read_json_line(
                    float(config.get("rvc_conversion_timeout") or 600)
                )
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or "RVC conversion failed")
                if not Path(output_path).is_file():
                    raise RuntimeError("RVC worker did not create an output file")
                self._last_error = None
                return True, None
            except Exception as exc:
                self._last_error = f"八重声线转换失败：{exc}"
                logger.warning(self._last_error)
                self.close()
                return False, self._last_error

    def close(self) -> None:
        process = self._process
        self._process = None
        self._signature = None
        self._stderr_thread = None
        if not process:
            return
        try:
            if process.poll() is None and process.stdin:
                process.stdin.write('{"command":"shutdown"}\n')
                process.stdin.flush()
                process.wait(timeout=3)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
