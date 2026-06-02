from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .deepseek_agents import (
    DeepSeekAgentConfig,
    ModelActionResult,
    call_player_action,
    estimate_usage_cost,
    sum_usage,
)
from .config import GameConfig, RuleConfig, roster_with_throw_score
from .report import write_accessible_report
from .simulator import FrisbeeSimulator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_STOP_FILES = [
    PROJECT_ROOT / "STOP_FRISBEE_GAME",
    WORKSPACE_ROOT / "STOP_FRISBEE_GAME",
]
FRAME_WAIT_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class LiveRunLimits:
    max_frames: int = 5
    max_api_calls: int = 50
    max_estimated_usd: float = 1.0
    timeout_seconds: float = 120.0
    history_frames: int = 8
    compact_history: bool = False
    throw_score_override: int | None = 100
    max_disc_speed_override: float | None = 18.0


@dataclass
class LiveRunStatus:
    running: bool = False
    stop_requested: bool = False
    run_id: str | None = None
    model: str = "deepseek-v4-flash"
    thinking: str = "disabled"
    max_tokens: int = 180
    frame: int = 0
    max_frames: int = 5
    history_frames: int = 8
    compact_history: bool = False
    throw_score_override: int | None = 100
    max_disc_speed_override: float | None = 18.0
    api_calls: int = 0
    estimated_cost_usd: float = 0.0
    last_frame_wall_seconds: float | None = None
    calls_ok_last_frame: int = 0
    calls_failed_last_frame: int = 0
    stop_reason: str | None = None
    log_path: str | None = None
    error: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    report_path: str | None = None
    agent_call_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage_totals: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
        }
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "stop_requested": self.stop_requested,
            "run_id": self.run_id,
            "model": self.model,
            "thinking": self.thinking,
            "max_tokens": self.max_tokens,
            "frame": self.frame,
            "max_frames": self.max_frames,
            "history_frames": self.history_frames,
            "compact_history": self.compact_history,
            "throw_score_override": self.throw_score_override,
            "max_disc_speed_override": self.max_disc_speed_override,
            "api_calls": self.api_calls,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "last_frame_wall_seconds": round(self.last_frame_wall_seconds, 3)
            if self.last_frame_wall_seconds is not None
            else None,
            "calls_ok_last_frame": self.calls_ok_last_frame,
            "calls_failed_last_frame": self.calls_failed_last_frame,
            "stop_reason": self.stop_reason,
            "log_path": self.log_path,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "report_path": self.report_path,
            "agent_call_status": self._agent_status_snapshot(),
            "usage_totals": dict(self.usage_totals),
        }

    def _agent_status_snapshot(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        snapshot: dict[str, dict[str, Any]] = {}
        for player_id, status in self.agent_call_status.items():
            item = dict(status)
            started_at = item.get("started_at")
            ended_at = item.get("ended_at")
            if isinstance(started_at, (int, float)):
                end = ended_at if isinstance(ended_at, (int, float)) else now
                item["elapsed_seconds"] = round(max(0.0, end - started_at), 3)
            snapshot[player_id] = item
        return snapshot


class DeepSeekGameRunner:
    def __init__(
        self,
        agent_config: DeepSeekAgentConfig,
        limits: LiveRunLimits | None = None,
        seed: int = 7,
        log_path: str | Path | None = None,
        stop_files: list[Path] | None = None,
    ) -> None:
        self.agent_config = agent_config
        self.limits = limits or LiveRunLimits()
        self.seed = seed
        self.stop_files = stop_files or DEFAULT_STOP_FILES
        self.stop_event = threading.Event()
        self.status = LiveRunStatus(
            model=agent_config.model,
            thinking=agent_config.thinking,
            max_tokens=agent_config.max_tokens,
            max_frames=self.limits.max_frames,
            history_frames=self.limits.history_frames,
            compact_history=self.limits.compact_history,
            throw_score_override=self.limits.throw_score_override,
            max_disc_speed_override=self.limits.max_disc_speed_override,
        )
        self.status_lock = threading.Lock()
        self.log_path = Path(log_path) if log_path else default_live_log_path()
        simulator_config = None
        roster = roster_with_throw_score(self.limits.throw_score_override) if self.limits.throw_score_override is not None else None
        rules = (
            RuleConfig(max_disc_speed_cells_per_frame=self.limits.max_disc_speed_override)
            if self.limits.max_disc_speed_override is not None
            else None
        )
        if roster is not None or rules is not None:
            simulator_config = GameConfig(roster=roster, rules=rules or RuleConfig())
        self.simulator = FrisbeeSimulator(config=simulator_config, seed=seed)

    def request_stop(self, reason: str = "manual_stop") -> None:
        self.stop_event.set()
        with self.status_lock:
            self.status.stop_requested = True
            if not self.status.stop_reason:
                self.status.stop_reason = reason

    def status_snapshot(self) -> dict[str, Any]:
        with self.status_lock:
            return self.status.as_dict()

    def run(self) -> LiveRunStatus:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.status_lock:
            self.status = LiveRunStatus(
                running=True,
                run_id=str(int(time.time())),
                model=self.agent_config.model,
                thinking=self.agent_config.thinking,
                max_tokens=self.agent_config.max_tokens,
                max_frames=self.limits.max_frames,
                history_frames=self.limits.history_frames,
                compact_history=self.limits.compact_history,
                throw_score_override=self.limits.throw_score_override,
                max_disc_speed_override=self.limits.max_disc_speed_override,
                log_path=str(self.log_path),
                started_at=time.time(),
            )
        try:
            with self.log_path.open("w", encoding="utf-8") as log_file:
                self._write_event(
                    log_file,
                    {
                        "type": "episode_start",
                        "seed": self.seed,
                        "model": self.agent_config.model,
                        "thinking": self.agent_config.thinking,
                        "max_tokens": self.agent_config.max_tokens,
                        "history_frames": self.limits.history_frames,
                        "compact_history": self.limits.compact_history,
                        "throw_score_override": self.limits.throw_score_override,
                        "max_disc_speed_override": self.limits.max_disc_speed_override,
                        "state": self.simulator.snapshot(),
                    },
                )
                self._run_frames(log_file)
                self._write_event(log_file, self._episode_end())
            report_path = write_accessible_report(self.log_path)
            with self.status_lock:
                self.status.report_path = str(report_path)
        except KeyboardInterrupt:
            self.request_stop("keyboard_interrupt")
            with self.status_lock:
                self.status.error = "Keyboard interrupt."
        except Exception as error:  # noqa: BLE001 - live run status should report unexpected failures.
            with self.status_lock:
                self.status.error = repr(error)
                self.status.stop_reason = "error"
        finally:
            if self.log_path.exists():
                try:
                    report_path = write_accessible_report(self.log_path)
                    with self.status_lock:
                        self.status.report_path = str(report_path)
                except Exception as error:  # noqa: BLE001 - report generation should not hide run status.
                    with self.status_lock:
                        self.status.error = self.status.error or f"Report generation failed: {error!r}"
            with self.status_lock:
                self.status.running = False
                self.status.ended_at = time.time()
        return self.status

    def _run_frames(self, log_file: Any) -> None:
        while not self.simulator.state.stopped:
            stop_reason = self._preflight_stop_reason()
            if stop_reason:
                with self.status_lock:
                    self.status.stop_reason = stop_reason
                break

            observations = {
                player_id: self.simulator.observation_for(
                    player_id,
                    history_frames=self.limits.history_frames,
                    compact_history=self.limits.compact_history,
                )
                for player_id in self.simulator.state.players
            }
            started = time.monotonic()
            results = self._call_frame(observations)
            wall_seconds = time.monotonic() - started
            if self.stop_event.is_set():
                self._record_aborted_frame(log_file, results, wall_seconds)
                break

            actions = {result.player_id: result.action for result in results}
            frame_result = self.simulator.step(actions)

            usage = sum_usage(results)
            cost = estimate_usage_cost(self.agent_config.model, usage) or 0.0
            self._add_usage(usage, cost)
            with self.status_lock:
                self.status.api_calls += len(results)
                self.status.frame = self.simulator.state.frame
                self.status.last_frame_wall_seconds = wall_seconds
                self.status.calls_ok_last_frame = sum(1 for result in results if result.ok)
                self.status.calls_failed_last_frame = sum(1 for result in results if not result.ok)

            event = frame_result.as_dict()
            event["model_results"] = [result.as_dict() for result in results]
            event["usage"] = usage
            event["estimated_cost_usd"] = cost
            with self.status_lock:
                event["cumulative_estimated_cost_usd"] = self.status.estimated_cost_usd
            event["wall_seconds"] = round(wall_seconds, 3)
            self._write_event(log_file, event)

            if self.simulator.state.stopped:
                with self.status_lock:
                    self.status.stop_reason = self.simulator.state.stop_reason
                break

        with self.status_lock:
            if not self.status.stop_reason:
                self.status.stop_reason = "complete"

    def _record_aborted_frame(self, log_file: Any, results: list[ModelActionResult], wall_seconds: float) -> None:
        usage = sum_usage(results)
        cost = estimate_usage_cost(self.agent_config.model, usage) or 0.0
        self._add_usage(usage, cost)
        with self.status_lock:
            self.status.api_calls += len(results)
            self.status.last_frame_wall_seconds = wall_seconds
            self.status.calls_ok_last_frame = sum(1 for result in results if result.ok)
            self.status.calls_failed_last_frame = sum(1 for result in results if not result.ok)
            stop_reason = self.status.stop_reason
            cumulative_cost = self.status.estimated_cost_usd
        self._write_event(
            log_file,
            {
                "type": "api_batch_aborted",
                "frame": self.simulator.state.frame,
                "stop_reason": stop_reason,
                "model_results": [result.as_dict() for result in results],
                "usage": usage,
                "estimated_cost_usd": cost,
                "cumulative_estimated_cost_usd": cumulative_cost,
                "wall_seconds": round(wall_seconds, 3),
            },
        )

    def _call_frame(self, observations: dict[str, dict[str, Any]]) -> list[ModelActionResult]:
        frame = self.simulator.state.frame
        with self.status_lock:
            self.status.agent_call_status = {
                player_id: {"state": "queued", "frame": frame, "started_at": None, "ended_at": None}
                for player_id in observations
            }

        def call_one(player_id: str, observation: dict[str, Any]) -> ModelActionResult:
            started_at = time.time()
            self._set_agent_call_status(player_id, {"state": "thinking", "frame": frame, "started_at": started_at})
            result = call_player_action(self.agent_config, player_id, observation)
            with self.status_lock:
                was_cancelled = self.status.agent_call_status.get(player_id, {}).get("state") == "cancelled"
            if not was_cancelled:
                self._set_agent_call_status(
                    player_id,
                    {
                        "state": "done" if result.ok else "error",
                        "frame": frame,
                        "started_at": started_at,
                        "ended_at": time.time(),
                        "latency_seconds": round(result.latency_seconds, 3),
                        "ok": result.ok,
                        "action": result.action.get("action"),
                        "error": result.error,
                    },
                )
            return result

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(observations))
        future_to_player = {
            executor.submit(call_one, player_id, observation): player_id
            for player_id, observation in observations.items()
        }
        pending = set(future_to_player)
        results: list[ModelActionResult] = []
        try:
            while pending:
                done, pending = concurrent.futures.wait(
                    pending,
                    timeout=FRAME_WAIT_POLL_SECONDS,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    results.append(future.result())

                if self.stop_event.is_set():
                    self._abandon_pending_calls(future_to_player, pending)
                    executor.shutdown(wait=False, cancel_futures=True)
                    return results
            executor.shutdown(wait=True)
            return results
        finally:
            if pending:
                executor.shutdown(wait=False, cancel_futures=True)

    def _abandon_pending_calls(
        self,
        future_to_player: dict[concurrent.futures.Future[ModelActionResult], str],
        pending: set[concurrent.futures.Future[ModelActionResult]],
    ) -> None:
        with self.status_lock:
            reason = self.status.stop_reason or "manual_stop"
        ended_at = time.time()
        for future in pending:
            future.cancel()
            self._set_agent_call_status(
                future_to_player[future],
                {
                    "state": "cancelled",
                    "ended_at": ended_at,
                    "ok": False,
                    "error": f"Stopped while waiting for provider response: {reason}",
                },
            )

    def _set_agent_call_status(self, player_id: str, status: dict[str, Any]) -> None:
        with self.status_lock:
            current = dict(self.status.agent_call_status.get(player_id, {}))
            current.update(status)
            self.status.agent_call_status[player_id] = current

    def _preflight_stop_reason(self) -> str | None:
        if self.stop_event.is_set():
            with self.status_lock:
                return self.status.stop_reason or "manual_stop"
        if any(path.exists() for path in self.stop_files):
            return "stop_file"
        if self.simulator.state.frame >= self.limits.max_frames:
            return "max_frames"
        with self.status_lock:
            api_calls = self.status.api_calls
            estimated_cost = self.status.estimated_cost_usd
        if api_calls + 10 > self.limits.max_api_calls:
            return "max_api_calls"
        if estimated_cost >= self.limits.max_estimated_usd:
            return "max_estimated_usd"
        return None

    def _add_usage(self, usage: dict[str, int], cost: float) -> None:
        with self.status_lock:
            for key, value in usage.items():
                self.status.usage_totals[key] = self.status.usage_totals.get(key, 0) + value
            self.status.estimated_cost_usd += cost

    def _episode_end(self) -> dict[str, Any]:
        with self.status_lock:
            return {
                "type": "episode_end",
                "frames": self.simulator.state.frame,
                "stopped": self.simulator.state.stopped,
                "score_team": self.simulator.state.score_team,
                "stop_reason": self.status.stop_reason,
                "throw_score_override": self.limits.throw_score_override,
                "max_disc_speed_override": self.limits.max_disc_speed_override,
                "history_frames": self.limits.history_frames,
                "compact_history": self.limits.compact_history,
                "api_calls": self.status.api_calls,
                "estimated_cost_usd": round(self.status.estimated_cost_usd, 6),
                "usage_totals": dict(self.status.usage_totals),
                "log_path": str(self.log_path),
                "report_path": self.status.report_path,
            }

    def _write_event(self, log_file: Any, event: dict[str, Any]) -> None:
        log_file.write(json.dumps(event, sort_keys=True) + "\n")
        log_file.flush()


def default_live_log_path() -> Path:
    return PROJECT_ROOT / "examples" / "runs" / "deepseek_live_latest.jsonl"
