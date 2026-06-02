from __future__ import annotations

import unittest

from frisbee_5v5.deepseek_agents import (
    DeepSeekAgentConfig,
    ModelActionResult,
    build_payload,
    normalize_usage,
    parse_model_action,
    stable_system_prompt,
)
from frisbee_5v5.config import GameConfig, roster_with_throw_score
from frisbee_5v5.simulator import FrisbeeSimulator


class DeepSeekAgentTests(unittest.TestCase):
    def test_parse_model_action_accepts_move_and_throw(self) -> None:
        move = parse_model_action('{"action":"move","target":{"x":10,"y":20},"reason":"cut"}')
        self.assertEqual(move["action"], "move")

        signal = parse_model_action('{"action":"signal_throw","intended_receiver":"blue_3","reason":"eye contact"}')
        self.assertEqual(signal["action"], "signal_throw")
        self.assertEqual(signal["intended_receiver"], "blue_3")

        throw = parse_model_action(
            '{"action":"throw","target":{"x":40,"y":20},"throw_side":"backhand","disc_speed":18,"reason":"lead"}'
        )
        self.assertEqual(throw["action"], "throw")
        self.assertIsNone(throw["intended_receiver"])

    def test_parse_model_action_rejects_bad_target(self) -> None:
        self.assertIsNone(parse_model_action('{"action":"move","target":{"x":10.5,"y":20},"reason":"bad"}'))
        self.assertIsNone(parse_model_action('{"action":"teleport","reason":"bad"}'))

    def test_payload_defaults_to_flash_non_thinking_json_mode(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        payload = build_payload(
            DeepSeekAgentConfig(api_key="secret"),
            "blue_1",
            simulator.observation_for("blue_1"),
        )
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("api_key", str(payload).lower())

    def test_stable_prompt_contains_roster_once(self) -> None:
        prompt = stable_system_prompt()
        self.assertIn("ROSTER", prompt)
        self.assertIn("The target coordinate sets the flight direction", prompt)
        self.assertIn("Passing is a two-frame commitment in v1.", prompt)
        self.assertIn("signal_throw", prompt)
        self.assertNotIn("STACK RULES", prompt)
        self.assertEqual(prompt.count("blue_1: captain"), 1)

    def test_prompt_uses_observation_roster_for_throw_override(self) -> None:
        simulator = FrisbeeSimulator(config=GameConfig(roster=roster_with_throw_score(100)), seed=7)
        payload = build_payload(
            DeepSeekAgentConfig(api_key="secret"),
            "blue_1",
            simulator.observation_for("blue_1"),
        )
        system_prompt = payload["messages"][0]["content"]
        self.assertIn("blue_1: captain yes, height 58, speed 63, throw 100", system_prompt)
        self.assertNotIn("blue_1: captain yes, height 58, speed 63, throw 88", system_prompt)

    def test_prompt_uses_observation_max_disc_speed(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        observation = simulator.observation_for("blue_1")
        observation["constants"]["max_disc_speed_cells_per_frame"] = 18
        payload = build_payload(DeepSeekAgentConfig(api_key="secret"), "blue_1", observation)
        system_prompt = payload["messages"][0]["content"]
        self.assertIn("Max disc speed is 18 cells per frame.", system_prompt)
        self.assertIn('"disc_speed":18', system_prompt)

    def test_normalize_usage_derives_cache_miss_from_cached_tokens(self) -> None:
        usage = normalize_usage(
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 30},
            }
        )
        self.assertEqual(usage["prompt_cache_hit_tokens"], 30)
        self.assertEqual(usage["prompt_cache_miss_tokens"], 70)

    def test_model_result_dict_keeps_raw_and_reasoning_content(self) -> None:
        result = ModelActionResult(
            player_id="blue_1",
            ok=True,
            latency_seconds=1.2345,
            status=200,
            action={"action": "hold", "reason": "wait"},
            raw_content='{"action":"hold","reason":"wait"}',
            reasoning_content="returned reasoning",
            finish_reason="stop",
        ).as_dict()
        self.assertEqual(result["latency_seconds"], 1.234)
        self.assertIn("raw_content", result)
        self.assertEqual(result["reasoning_content"], "returned reasoning")


if __name__ == "__main__":
    unittest.main()
