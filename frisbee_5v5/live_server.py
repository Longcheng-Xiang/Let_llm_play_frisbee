from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .deepseek_agents import DeepSeekAgentConfig
from .deepseek_probe import get_api_key
from .live_runner import DEFAULT_STOP_FILES, PROJECT_ROOT, DeepSeekGameRunner, LiveRunLimits, default_live_log_path
from .live_runner_v2 import DeepSeekGameRunnerV2, default_live_v2_log_path
from .report import write_accessible_report


NON_THINKING_MAX_TOKENS_DEFAULT = 180
THINKING_MAX_TOKENS_DEFAULT = 8000
DEFAULT_GAME_VERSION = "v2_awake_sleep"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_THINKING = "enabled"
DEFAULT_MAX_FRAMES = 20
DEFAULT_HISTORY_FRAMES = 4


def default_max_tokens_for_thinking(thinking: str) -> int:
    return THINKING_MAX_TOKENS_DEFAULT if thinking == "enabled" else NON_THINKING_MAX_TOKENS_DEFAULT


class LiveRunController:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.runner: DeepSeekGameRunner | None = None
        self.thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            if not self.runner:
                log_path = default_log_path_for_game_version(DEFAULT_GAME_VERSION)
                return {
                    "running": False,
                    "stop_requested": False,
                    "run_id": None,
                    "game_version": DEFAULT_GAME_VERSION,
                    "model": DEFAULT_MODEL,
                    "thinking": DEFAULT_THINKING,
                    "max_tokens": default_max_tokens_for_thinking(DEFAULT_THINKING),
                    "frame": 0,
                    "max_frames": DEFAULT_MAX_FRAMES,
                    "history_frames": DEFAULT_HISTORY_FRAMES,
                    "compact_history": False,
                    "throw_score_override": 100,
                    "max_disc_speed_override": 18.0,
                    "api_calls": 0,
                    "estimated_cost_usd": 0.0,
                    "last_frame_wall_seconds": None,
                    "calls_ok_last_frame": 0,
                    "calls_failed_last_frame": 0,
                    "stop_reason": None,
                    "log_path": str(log_path) if log_path.exists() else None,
                    "error": None,
                    "report_path": str(report_path_for(log_path)) if report_path_for(log_path).exists() else None,
                    "agent_call_status": {},
                    "usage_totals": {},
                }
            status = self.runner.status_snapshot()
            status.setdefault("game_version", "v1_roleless")
            return status

    def start(self, options: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.runner and self.runner.status.running:
                return {"ok": False, "error": "A live run is already running.", "status": self.runner.status.as_dict()}

            api_key = get_api_key()
            if not api_key:
                return {"ok": False, "error": "No DEEPSEEK_API_KEY found in environment or project .env."}

            clear_stop_files()
            game_version = str(options.get("game_version") or DEFAULT_GAME_VERSION)
            use_v2 = game_version in {"v2", "v2_awake_sleep"}
            model = str(options.get("model") or DEFAULT_MODEL)
            thinking = str(options.get("thinking") or DEFAULT_THINKING)
            max_frames = bounded_int(options.get("max_frames"), default=DEFAULT_MAX_FRAMES, low=1, high=50)
            history_frames = bounded_int(options.get("history_frames"), default=DEFAULT_HISTORY_FRAMES, low=0, high=20)
            compact_history = bool(options.get("compact_history", False))
            throw_score_override = bounded_int(options.get("throw_score_override"), default=100, low=0, high=100)
            max_disc_speed_override = bounded_float(options.get("max_disc_speed_override"), default=18.0, low=0.0, high=30.0)
            max_api_calls = bounded_int(options.get("max_api_calls"), default=max_frames * 10, low=10, high=500)
            max_estimated_usd = bounded_float(options.get("max_estimated_usd"), default=1.0, low=0.01, high=20.0)
            seed = bounded_int(options.get("seed"), default=7, low=0, high=1_000_000)
            timeout = bounded_float(options.get("timeout_seconds"), default=120.0, low=10.0, high=600.0)
            max_tokens = bounded_int(
                options.get("max_tokens"),
                default=default_max_tokens_for_thinking(thinking),
                low=40,
                high=32000,
            )
            log_path = Path(options.get("log_path") or (default_live_v2_log_path() if use_v2 else default_live_log_path()))

            runner_class = DeepSeekGameRunnerV2 if use_v2 else DeepSeekGameRunner
            self.runner = runner_class(
                DeepSeekAgentConfig(
                    api_key=api_key,
                    model=model,
                    timeout=timeout,
                    thinking=thinking,
                    max_tokens=max_tokens,
                ),
                limits=LiveRunLimits(
                    max_frames=max_frames,
                    max_api_calls=max_api_calls,
                    max_estimated_usd=max_estimated_usd,
                    timeout_seconds=timeout,
                    history_frames=history_frames,
                    compact_history=compact_history,
                    throw_score_override=throw_score_override or None,
                    max_disc_speed_override=max_disc_speed_override or None,
                ),
                seed=seed,
                log_path=log_path,
            )
            self.thread = threading.Thread(target=self.runner.run, name="deepseek-live-run", daemon=True)
            self.thread.start()
            return {"ok": True, "status": self.runner.status_snapshot()}

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if not self.runner:
                return {"ok": True, "status": {"running": False, "stop_requested": False}}
            self.runner.request_stop("ui_stop")
            return {"ok": True, "status": self.runner.status_snapshot()}

    def replay_text(self) -> str:
        with self.lock:
            path = (
                Path(self.runner.status.log_path)
                if self.runner and self.runner.status.log_path
                else default_log_path_for_game_version(DEFAULT_GAME_VERSION)
            )
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def report_html(self) -> str:
        with self.lock:
            path = (
                Path(self.runner.status.log_path)
                if self.runner and self.runner.status.log_path
                else default_log_path_for_game_version(DEFAULT_GAME_VERSION)
            )
        if not path.exists():
            return "<!doctype html><title>No report</title><p>No live log exists yet.</p>"
        report_path = write_accessible_report(path)
        return report_path.read_text(encoding="utf-8")


def make_handler(controller: LiveRunController) -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            if self.path == "/api/trial/status":
                self.send_json(controller.status())
                return
            if self.path == "/api/trial/replay":
                text = controller.replay_text()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-jsonlines; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(text.encode("utf-8"))
                return
            if self.path == "/api/trial/report":
                html = controller.report_html()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
            if self.path == "/api/trial/start":
                self.send_json(controller.start(self.read_json_body()))
                return
            if self.path == "/api/trial/stop":
                self.send_json(controller.stop())
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def read_json_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length")
            if not raw_length:
                return {}
            try:
                raw = self.rfile.read(int(raw_length)).decode("utf-8")
                parsed = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8766) -> None:
    controller = LiveRunController()
    server = ThreadingHTTPServer((host, port), make_handler(controller))
    print(f"Frisbee live trial server: http://{host}:{port}/viewer/")
    print("UI Stop abandons active waits and prevents new frames; Ctrl+C stops the server.")
    print("Terminal hard stop: touch STOP_FRISBEE_GAME in the project or workspace root.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        controller.stop()
        print("\nStopping live trial server.")
    finally:
        server.server_close()


def clear_stop_files() -> None:
    for path in DEFAULT_STOP_FILES:
        if path.exists():
            path.unlink()


def report_path_for(log_path: Path) -> Path:
    return log_path.with_name(f"{log_path.stem}_report.html")


def default_log_path_for_game_version(game_version: str) -> Path:
    return default_live_v2_log_path() if game_version in {"v2", "v2_awake_sleep"} else default_live_log_path()


def bounded_int(value: object, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, low), high)


def bounded_float(value: object, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, low), high)
