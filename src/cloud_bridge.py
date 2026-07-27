"""Secure outbound bridge between the local Flask app and the cloud relay."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import platform
import queue
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import requests
import websocket


LOGGER = logging.getLogger("shengyue.cloud_bridge")
ALLOWED_PATH_PREFIXES = ("/api/", "/files/", "/static/audio/", "/healthz", "/readyz")
SAFE_RESPONSE_HEADERS = {
    "content-type",
    "content-disposition",
    "cache-control",
    "content-range",
    "accept-ranges",
}
KEYCHAIN_BRIDGE_URL_SERVICE = "ShengYue Cloud Bridge URL"
KEYCHAIN_BRIDGE_SECRET_SERVICE = "ShengYue Cloud Bridge Secret"


def _keychain_value(service: str) -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _path_allowed(path: str) -> bool:
    parsed = urlparse(path)
    return any(parsed.path == prefix or parsed.path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


class CloudBridge:
    def __init__(self, relay_url: str, secret: str, local_url: str) -> None:
        self.relay_url = relay_url.rstrip("/")
        self.secret = secret
        self.local_url = local_url.rstrip("/")
        self.stop_event = threading.Event()
        self.socket: websocket.WebSocketApp | None = None
        self.send_queue: queue.Queue[str] = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cloud-proxy")

    @property
    def websocket_url(self) -> str:
        if self.relay_url.startswith("https://"):
            return "wss://" + self.relay_url.removeprefix("https://") + "/bridge/connect"
        if self.relay_url.startswith("http://"):
            return "ws://" + self.relay_url.removeprefix("http://") + "/bridge/connect"
        raise ValueError("Cloud relay URL must start with http:// or https://")

    def send(self, payload: dict[str, Any]) -> None:
        self.send_queue.put(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def _sender(self, ws: websocket.WebSocketApp) -> None:
        while not self.stop_event.is_set() and ws.sock and ws.sock.connected:
            try:
                payload = self.send_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                ws.send(payload)
            except Exception:
                self.send_queue.put(payload)
                return

    def _heartbeat(self, ws: websocket.WebSocketApp) -> None:
        while not self.stop_event.wait(20):
            if not ws.sock or not ws.sock.connected:
                return
            self.send({"type": "heartbeat", "at": time.time()})

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        self.send({
            "type": "auth",
            "secret": self.secret,
            "name": platform.node() or "本地声阅",
            "version": os.environ.get("SHENGYUE_VERSION", "dev"),
        })
        threading.Thread(target=self._sender, args=(ws,), daemon=True).start()
        threading.Thread(target=self._heartbeat, args=(ws,), daemon=True).start()

    def _on_message(self, _ws: websocket.WebSocketApp, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("Ignored an invalid relay message.")
            return
        if message.get("type") == "auth_ok":
            LOGGER.info("Cloud bridge connected. The online app can now use this Mac.")
            return
        if message.get("type") != "request":
            return
        self.executor.submit(self._handle_request, message)

    def _handle_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id") or "")
        path = str(message.get("path") or "")
        if not request_id or not _path_allowed(path):
            self.send({"type": "response_error", "id": request_id, "error": "Blocked local path."})
            return
        try:
            body = base64.b64decode(message.get("body") or "", validate=True)
            headers = {
                str(name): str(value)
                for name, value in (message.get("headers") or {}).items()
                if str(name).lower() not in {"host", "content-length", "connection", "cookie", "authorization"}
            }
            response = requests.request(
                method=str(message.get("method") or "GET"),
                url=self.local_url + path,
                headers=headers,
                data=body or None,
                stream=True,
                timeout=(15, 30 * 60),
                allow_redirects=False,
            )
            response_headers = {
                name: value
                for name, value in response.headers.items()
                if name.lower() in SAFE_RESPONSE_HEADERS
            }
            self.send({
                "type": "response_start",
                "id": request_id,
                "status": response.status_code,
                "headers": response_headers,
            })
            for chunk in response.iter_content(chunk_size=384 * 1024):
                if chunk:
                    self.send({
                        "type": "response_chunk",
                        "id": request_id,
                        "data": base64.b64encode(chunk).decode("ascii"),
                    })
            self.send({"type": "response_end", "id": request_id})
        except Exception as exc:  # noqa: BLE001 - boundary reports a safe generic error
            LOGGER.warning("Local request failed: %s", exc)
            self.send({"type": "response_error", "id": request_id, "error": "本地处理失败，请查看电脑上的声阅日志。"})

    def _on_error(self, _ws: websocket.WebSocketApp, error: Exception) -> None:
        if not self.stop_event.is_set():
            LOGGER.warning("Cloud bridge connection error: %s", error)

    def _on_close(self, _ws: websocket.WebSocketApp, code: int, reason: str) -> None:
        if not self.stop_event.is_set():
            LOGGER.info("Cloud bridge disconnected (%s %s). Reconnecting…", code, reason or "")

    def run(self) -> None:
        delay = 2
        while not self.stop_event.is_set():
            self.socket = websocket.WebSocketApp(
                self.websocket_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self.socket.run_forever(
                ping_interval=25,
                ping_timeout=10,
                sslopt={"ca_certs": requests.certs.where()},
            )
            if self.stop_event.wait(delay):
                break
            delay = min(delay * 2, 30)

    def stop(self) -> None:
        self.stop_event.set()
        if self.socket:
            self.socket.close()
        self.executor.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect local ShengYue to its secure cloud relay.")
    parser.add_argument("--relay-url", default=os.environ.get("SHENGYUE_CLOUD_RELAY_URL") or _keychain_value(KEYCHAIN_BRIDGE_URL_SERVICE))
    parser.add_argument("--secret", default=os.environ.get("SHENGYUE_CLOUD_BRIDGE_SECRET") or _keychain_value(KEYCHAIN_BRIDGE_SECRET_SERVICE))
    parser.add_argument("--local-url", default=os.environ.get("SHENGYUE_LOCAL_URL", "http://127.0.0.1:7860"))
    args = parser.parse_args()
    if not args.relay_url or not args.secret:
        parser.error(
            "Cloud bridge is not configured. Set SHENGYUE_CLOUD_RELAY_URL and "
            "SHENGYUE_CLOUD_BRIDGE_SECRET, or store them in macOS Keychain."
        )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bridge = CloudBridge(args.relay_url, args.secret, args.local_url)

    def stop_bridge(_signum: int, _frame: Any) -> None:
        bridge.stop()

    signal.signal(signal.SIGINT, stop_bridge)
    signal.signal(signal.SIGTERM, stop_bridge)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
