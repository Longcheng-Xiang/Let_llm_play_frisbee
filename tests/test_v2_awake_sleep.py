from __future__ import annotations

import json
import unittest
from dataclasses import replace

from frisbee_5v5.awake_controller import AwakeSleepController
from frisbee_5v5.config import GameConfig, INITIAL_POSITIONS, ROSTER, RuleConfig
from frisbee_5v5.deepseek_agents import DeepSeekAgentConfig
from frisbee_5v5.deepseek_agents_v2 import build_payload_v2, parse_model_action_v2
from frisbee_5v5.simulator import FrisbeeSimulator


def custom_config(
    positions: dict[str, tuple[int, int]] | None = None,
    roster_updates: dict[str, dict[str, int]] | None = None,
    rules: RuleConfig | None = None,
) -> GameConfig:
    roster = dict(ROSTER)
    for player_id, updates in (roster_updates or {}).items():
        roster[player_id] = replace(roster[player_id], **updates)
    merged_positions = dict(INITIAL_POSITIONS)
    if positions:
        merged_positions.update(positions)
    return GameConfig(roster=roster, initial_positions=merged_positions, rules=rules or RuleConfig())


class V2AwakeSleepTests(unittest.TestCase):
    def test_v2_parser_accepts_move_intent(self) -> None:
        action = parse_model_action_v2(
            '{"action":"move_intent","target":{"x":82,"y":31},"duration_frames":4,"reason":"continue cut"}'
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "move_intent")
        self.assertEqual(action["duration_frames"], 4)

    def test_v2_parser_rounds_float_grid_targets(self) -> None:
        action = parse_model_action_v2(
            '{"action":"move","target":{"x":69.932,"y":38.949},"reason":"intercept disc"}'
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["target"], {"x": 70, "y": 39})

    def test_v2_parser_repairs_obvious_malformed_action(self) -> None:
        action = parse_model_action_v2(
            '{"action":"move","target":{"x":150,"y":37},"reason":"Run to x=150" as intended receiver"}'
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "move")
        self.assertEqual(action["target"], {"x": 150, "y": 37})

    def test_v2_payload_contains_awake_context_and_intent_board(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        controller = AwakeSleepController()
        decision = controller.decide_awake_players(simulator)
        observation = controller.augment_observation(
            simulator,
            "blue_1",
            simulator.observation_for("blue_1"),
            decision,
        )
        payload = build_payload_v2(DeepSeekAgentConfig(api_key="secret"), "blue_1", observation)
        user_packet = payload["messages"][1]["content"]
        packet = json.loads(user_packet)
        self.assertIn("awake_context", user_packet)
        self.assertIn("teammate_movement_intents", user_packet)
        self.assertIn("passing_options", user_packet)
        self.assertIn("fixed_defender", user_packet)
        self.assertIn("move_intent", payload["messages"][0]["content"])
        self.assertIn("Stall 5", payload["messages"][0]["content"])
        self.assertIn("you may choose hold, talk, or signal_throw", payload["messages"][0]["content"])
        self.assertNotIn(
            "choose signal_throw to establish private eye contact",
            payload["messages"][0]["content"],
        )
        self.assertEqual(
            packet["player_decision_context"]["decision_request"]["preferred_action_style"],
            "thrower_decision",
        )
        self.assertIn("Before choosing signal_throw or throw", user_packet)
        self.assertIn("Do not treat signal_throw as mandatory", user_packet)
        self.assertIn("current_state.stall.remaining", payload["messages"][0]["content"])

    def test_v2_payload_keeps_shared_frame_context_before_player_specific_context(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        controller = AwakeSleepController()
        decision = controller.decide_awake_players(simulator)
        blue_2_observation = controller.augment_observation(
            simulator,
            "blue_2",
            simulator.observation_for("blue_2"),
            decision,
        )
        blue_3_observation = controller.augment_observation(
            simulator,
            "blue_3",
            simulator.observation_for("blue_3"),
            decision,
        )

        blue_2_content = build_payload_v2(DeepSeekAgentConfig(api_key="secret"), "blue_2", blue_2_observation)[
            "messages"
        ][1]["content"]
        blue_3_content = build_payload_v2(DeepSeekAgentConfig(api_key="secret"), "blue_3", blue_3_observation)[
            "messages"
        ][1]["content"]

        split_marker = ',"player_decision_context":'
        self.assertTrue(blue_2_content.startswith('{"shared_frame_context":'))
        self.assertIn(split_marker, blue_2_content)
        self.assertEqual(blue_2_content.split(split_marker, 1)[0], blue_3_content.split(split_marker, 1)[0])

    def test_v2_shared_frame_context_does_not_leak_private_eye_contact(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        simulator.step({"blue_1": {"action": "signal_throw", "intended_receiver": "blue_3"}})
        controller = AwakeSleepController()
        decision = controller.decide_awake_players(simulator)
        observation = controller.augment_observation(
            simulator,
            "red_2",
            simulator.observation_for("red_2"),
            decision,
        )

        content = build_payload_v2(DeepSeekAgentConfig(api_key="secret"), "red_2", observation)["messages"][1][
            "content"
        ]
        packet = json.loads(content)
        shared = packet["shared_frame_context"]
        private = packet["player_decision_context"]
        self.assertIsNone(shared["current_state"]["pending_pass"])
        self.assertIsNone(private["current_state_private_for_you"]["pending_pass"])

    def test_v2_defender_payload_surfaces_marking_distance_and_recovery_target(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        controller = AwakeSleepController()
        decision = controller.decide_awake_players(simulator)
        observation = controller.augment_observation(
            simulator,
            "red_3",
            simulator.observation_for("red_3"),
            decision,
        )

        payload = build_payload_v2(DeepSeekAgentConfig(api_key="secret"), "red_3", observation)
        packet = json.loads(payload["messages"][1]["content"])
        marking = packet["player_decision_context"]["tactical_context"]["defensive_marking"]
        important = packet["player_decision_context"]["decision_request"]["important"]

        self.assertEqual(marking["matchup"], "blue_3")
        self.assertEqual(marking["recovery_target_this_frame"], {"x": 60, "y": 31})
        self.assertIn("distance_to_matchup", marking)
        self.assertTrue(any("outside marking radius" in item for item in important))
        self.assertIn("tactical_context.defensive_marking", payload["messages"][0]["content"])

    def test_eye_contact_locks_receiver_intent_through_release_frame(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        controller = AwakeSleepController()
        decision = controller.decide_awake_players(simulator)
        actions = controller.actions_for_frame(
            simulator,
            {
                "blue_1": {"action": "signal_throw", "intended_receiver": "blue_3", "reason": "lead active cut"},
                "blue_3": {
                    "action": "move_intent",
                    "target": {"x": 80, "y": 31},
                    "duration_frames": 1,
                    "reason": "one-frame cut that should be locked",
                },
            },
            decision,
        )
        result = simulator.step(actions)
        controller.update_after_frame(simulator, result)

        next_decision = controller.decide_awake_players(simulator)
        self.assertEqual(next_decision.wake_reasons_by_player["blue_1"], "committed_thrower")
        self.assertEqual(next_decision.wake_reasons_by_player["blue_3"], "eye_contact_receiver")
        board = controller.teammate_intent_board(simulator, "blue_1")
        blue_3 = next(item for item in board if item["player_id"] == "blue_3")
        self.assertTrue(blue_3["has_active_intent"])
        self.assertEqual(blue_3["frames_remaining"], 1)

    def test_v2_disc_contest_only_uses_intended_receiver_and_fixed_defender(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={
                    "blue_1": (10, 10),
                    "blue_3": (80, 30),
                    "red_3": (80, 45),
                    "red_5": (20, 10),
                    "red_2": (5, 10),
                },
                roster_updates={"blue_1": {"throw": 100}},
                rules=RuleConfig(
                    max_disc_speed_cells_per_frame=30,
                    restrict_disc_contest_to_intended_pair=True,
                ),
            ),
            seed=7,
        )
        simulator.step({"blue_1": {"action": "signal_throw", "intended_receiver": "blue_3"}})
        result = simulator.step(
            {
                "blue_1": {
                    "action": "throw",
                    "target": {"x": 40, "y": 10},
                    "intended_receiver": "blue_3",
                    "throw_side": "forehand",
                    "disc_speed": 30,
                }
            }
        )

        self.assertIsNone(simulator.state.disc.holder)
        self.assertTrue(any(event["type"] == "disc_flying" for event in result.events))
        self.assertFalse(any(event["type"] == "defensive_block" and event["player"] == "red_5" for event in result.events))


if __name__ == "__main__":
    unittest.main()
