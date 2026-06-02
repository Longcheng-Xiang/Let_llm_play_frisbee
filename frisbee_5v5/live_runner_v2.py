from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from pathlib import Path
from typing import Any

from .awake_controller import AwakeSleepController, WakeDecision
from .config import GameConfig, RuleConfig, roster_with_throw_score
from .deepseek_agents_v2 import (
    DeepSeekAgentConfig,
    ModelActionResult,
    call_player_action_v2,
    estimate_usage_cost,
    sum_usage,
)
from .live_runner import DEFAULT_STOP_FILES, FRAME_WAIT_POLL_SECONDS, LiveRunLimits, LiveRunStatus, PROJECT_ROOT
from .report import write_accessible_report
from .simulator import FrisbeeSimulator


class DeepSeekGameRunnerV2:
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
        self.log_path = Path(log_path) if log_path else default_live_v2_log_path()
        roster = roster_with_throw_score(self.limits.throw_score_override) if self.limits.throw_score_override is not None else None
        rules = RuleConfig(
            max_disc_speed_cells_per_frame=self.limits.max_disc_speed_override
            if self.limits.max_disc_speed_override is not None
            else RuleConfig().max_disc_speed_cells_per_frame,
            restrict_disc_contest_to_intended_pair=True,
        )
        self.simulator = FrisbeeSimulator(config=GameConfig(roster=roster, rules=rules), seed=seed)
        self.controller = AwakeSleepController()

    def request_stop(self, reason: str = "manual_stop") -> None:
        self.stop_event.set()
        with self.status_lock:
            self.status.stop_requested = True
            if not self.status.stop_reason:
                self.status.stop_reason = reason

    def status_snapshot(self) -> dict[str, Any]:
        with self.status_lock:
            status = self.status.as_dict()
        status["game_version"] = "v2_awake_sleep"
        return status

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
                        "game_version": "v2_awake_sleep",
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
        except Exception as error:  # noqa: BLE001
            with self.status_lock:
                self.status.error = repr(error)
                self.status.stop_reason = "error"
        finally:
            if self.log_path.exists():
                try:
                    report_path = write_accessible_report(self.log_path)
                    with self.status_lock:
                        self.status.report_path = str(report_path)
                except Exception as error:  # noqa: BLE001
                    with self.status_lock:
                        self.status.error = self.status.error or f"Report generation failed: {error!r}"
            with self.status_lock:
                self.status.running = False
                self.status.ended_at = time.time()
        return self.status

    def _run_frames(self, log_file: Any) -> None:
        while not self.simulator.state.stopped:
            stop_reason = self._preflight_stop_reason(next_api_calls=0)
            if stop_reason:
                with self.status_lock:
                    self.status.stop_reason = stop_reason
                break

            decision = self.controller.decide_awake_players(self.simulator)
            observations = {
                player_id: self.controller.augment_observation(
                    self.simulator,
                    player_id,
                    self.simulator.observation_for(
                        player_id,
                        history_frames=self.limits.history_frames,
                        compact_history=self.limits.compact_history,
                    ),
                    decision,
                )
                for player_id in sorted(decision.awake_players)
            }

            stop_reason = self._preflight_stop_reason(next_api_calls=len(observations))
            if stop_reason:
                with self.status_lock:
                    self.status.stop_reason = stop_reason
                break

            intent_board_before = self.controller.intent_board(self.simulator)
            started = time.monotonic()
            results = self._call_frame(observations, decision)
            wall_seconds = time.monotonic() - started
            if self.stop_event.is_set():
                self._record_aborted_frame(log_file, results, wall_seconds, decision, intent_board_before)
                break

            model_actions = {result.player_id: result.action for result in results}
            actions = self.controller.actions_for_frame(self.simulator, model_actions, decision)
            frame_result = self.simulator.step(actions)
            self.controller.update_after_frame(self.simulator, frame_result)

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
            event["game_version"] = "v2_awake_sleep"
            event["model_results"] = [result.as_dict() for result in results]
            event["usage"] = usage
            event["estimated_cost_usd"] = cost
            with self.status_lock:
                event["cumulative_estimated_cost_usd"] = self.status.estimated_cost_usd
            event["wall_seconds"] = round(wall_seconds, 3)
            event["awake_sleep"] = {
                "awake_players": sorted(decision.awake_players),
                "sleeping_players": sorted(set(self.simulator.state.players) - decision.awake_players),
                "wake_reasons_by_player": dict(sorted(decision.wake_reasons_by_player.items())),
                "intent_board_before": intent_board_before,
                "controller": self.controller.snapshot(),
            }
            self._write_event(log_file, event)

            if self.simulator.state.stopped:
                with self.status_lock:
                    self.status.stop_reason = self.simulator.state.stop_reason
                break

        with self.status_lock:
            if not self.status.stop_reason:
                self.status.stop_reason = "complete"

    def _record_aborted_frame(
        self,
        log_file: Any,
        results: list[ModelActionResult],
        wall_seconds: float,
        decision: WakeDecision,
        intent_board_before: dict[str, Any],
    ) -> None:
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
                "game_version": "v2_awake_sleep",
                "frame": self.simulator.state.frame,
                "stop_reason": stop_reason,
                "model_results": [result.as_dict() for result in results],
                "usage": usage,
                "estimated_cost_usd": cost,
                "cumulative_estimated_cost_usd": cumulative_cost,
                "wall_seconds": round(wall_seconds, 3),
                "awake_sleep": {
                    "awake_players": sorted(decision.awake_players),
                    "sleeping_players": sorted(set(self.simulator.state.players) - decision.awake_players),
                    "wake_reasons_by_player": dict(sorted(decision.wake_reasons_by_player.items())),
                    "intent_board_before": intent_board_before,
                    "controller": self.controller.snapshot(),
                },
            },
        )

    def _call_frame(self, observations: dict[str, dict[str, Any]], decision: WakeDecision) -> list[ModelActionResult]:
        frame = self.simulator.state.frame
        all_players = set(self.simulator.state.players)
        with self.status_lock:
            self.status.agent_call_status = {
                player_id: {
                    "state": "queued" if player_id in observations else "sleeping",
                    "frame": frame,
                    "started_at": None,
                    "ended_at": None,
                    "wake_reason": decision.wake_reasons_by_player.get(player_id),
                }
                for player_id in sorted(all_players)
            }

        if not observations:
            return []

        def call_one(player_id: str, observation: dict[str, Any]) -> ModelActionResult:
            started_at = time.time()
            self._set_agent_call_status(player_id, {"state": "thinking", "frame": frame, "started_at": started_at})
            result = call_player_action_v2(self.agent_config, player_id, observation)
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

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(observations)))
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

    def _preflight_stop_reason(self, next_api_calls: int) -> str | None:
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
        if next_api_calls and api_calls + next_api_calls > self.limits.max_api_calls:
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
                "game_version": "v2_awake_sleep",
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


def default_live_v2_log_path() -> Path:
    return PROJECT_ROOT / "examples" / "runs" / "deepseek_v2_live_latest.jsonl"
