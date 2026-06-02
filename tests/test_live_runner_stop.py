from __future__ import annotations

import threading
import unittest

import frisbee_5v5.live_runner as live_runner_module
import frisbee_5v5.live_runner_v2 as live_runner_v2_module
from frisbee_5v5.awake_controller import WakeDecision
from frisbee_5v5.deepseek_agents import DeepSeekAgentConfig, ModelActionResult
from frisbee_5v5.live_runner import DeepSeekGameRunner
from frisbee_5v5.live_runner_v2 import DeepSeekGameRunnerV2


def blocked_result(player_id: str) -> ModelActionResult:
    return ModelActionResult(
        player_id=player_id,
        ok=True,
        latency_seconds=0.0,
        status=200,
        action={"action": "hold", "reason": "fake result"},
    )


class LiveRunnerStopTests(unittest.TestCase):
    def test_v1_call_frame_abandons_pending_provider_wait_after_stop(self) -> None:
        runner = DeepSeekGameRunner(DeepSeekAgentConfig(api_key="secret"))
        started = threading.Event()
        release = threading.Event()
        original = live_runner_module.call_player_action
        holder: dict[str, object] = {}

        def fake_call(config: DeepSeekAgentConfig, player_id: str, observation: dict[str, object]) -> ModelActionResult:
            started.set()
            release.wait(timeout=5)
            return blocked_result(player_id)

        def run_call_frame() -> None:
            try:
                holder["results"] = runner._call_frame({"blue_1": {}})
            except BaseException as error:  # noqa: BLE001 - preserve thread error for assertion.
                holder["error"] = error

        live_runner_module.call_player_action = fake_call
        thread = threading.Thread(target=run_call_frame)
        try:
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            runner.request_stop("ui_stop")
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertNotIn("error", holder)
            self.assertEqual(holder["results"], [])
            status = runner.status_snapshot()["agent_call_status"]["blue_1"]
            self.assertEqual(status["state"], "cancelled")
            self.assertIn("ui_stop", status["error"])
        finally:
            release.set()
            thread.join(timeout=2)
            live_runner_module.call_player_action = original

    def test_v2_call_frame_abandons_pending_provider_wait_after_stop(self) -> None:
        runner = DeepSeekGameRunnerV2(DeepSeekAgentConfig(api_key="secret"))
        started = threading.Event()
        release = threading.Event()
        original = live_runner_v2_module.call_player_action_v2
        holder: dict[str, object] = {}

        def fake_call(config: DeepSeekAgentConfig, player_id: str, observation: dict[str, object]) -> ModelActionResult:
            started.set()
            release.wait(timeout=5)
            return blocked_result(player_id)

        def run_call_frame() -> None:
            try:
                holder["results"] = runner._call_frame(
                    {"blue_1": {}},
                    WakeDecision(awake_players={"blue_1"}, wake_reasons_by_player={"blue_1": "test"}),
                )
            except BaseException as error:  # noqa: BLE001 - preserve thread error for assertion.
                holder["error"] = error

        live_runner_v2_module.call_player_action_v2 = fake_call
        thread = threading.Thread(target=run_call_frame)
        try:
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            runner.request_stop("ui_stop")
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertNotIn("error", holder)
            self.assertEqual(holder["results"], [])
            status = runner.status_snapshot()["agent_call_status"]["blue_1"]
            self.assertEqual(status["state"], "cancelled")
            self.assertIn("ui_stop", status["error"])
        finally:
            release.set()
            thread.join(timeout=2)
            live_runner_v2_module.call_player_action_v2 = original


if __name__ == "__main__":
    unittest.main()
