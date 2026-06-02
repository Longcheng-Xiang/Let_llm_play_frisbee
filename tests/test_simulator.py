from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from frisbee_5v5.config import GameConfig, INITIAL_POSITIONS, ROSTER, max_move_cells_for_speed, roster_with_throw_score
from frisbee_5v5.policies import HeuristicPolicy
from frisbee_5v5.simulator import DiscState, FrisbeeSimulator


class FixedRng:
    def __init__(self, random_values: list[float] | None = None, choice_value: str | None = None) -> None:
        self.random_values = list(random_values or [0.0])
        self.choice_value = choice_value
        self.choice_calls = 0

    def random(self) -> float:
        if len(self.random_values) == 1:
            return self.random_values[0]
        return self.random_values.pop(0)

    def gauss(self, mu: float, sigma: float) -> float:
        return mu

    def choice(self, values: list[str]) -> str:
        self.choice_calls += 1
        if self.choice_value is not None:
            return self.choice_value
        return values[0]


def custom_config(
    positions: dict[str, tuple[int, int]] | None = None,
    roster_updates: dict[str, dict[str, int]] | None = None,
) -> GameConfig:
    roster = dict(ROSTER)
    for player_id, updates in (roster_updates or {}).items():
        roster[player_id] = replace(roster[player_id], **updates)
    merged_positions = dict(INITIAL_POSITIONS)
    if positions:
        merged_positions.update(positions)
    return GameConfig(roster=roster, initial_positions=merged_positions)


def signal_then_throw(simulator: FrisbeeSimulator, throw_action: dict[str, Any]) -> Any:
    simulator.step(
        {
            "blue_1": {
                "action": "signal_throw",
                "intended_receiver": throw_action.get("intended_receiver"),
                "reason": "commit pass",
            }
        }
    )
    return simulator.step({"blue_1": throw_action})


class SimulatorTests(unittest.TestCase):
    def test_speed_mapping_is_coarse(self) -> None:
        self.assertEqual(max_move_cells_for_speed(20), 6)
        self.assertEqual(max_move_cells_for_speed(21), 8)
        self.assertEqual(max_move_cells_for_speed(60), 10)
        self.assertEqual(max_move_cells_for_speed(61), 12)
        self.assertEqual(max_move_cells_for_speed(100), 14)

    def test_roster_throw_score_override_preserves_other_attributes(self) -> None:
        roster = roster_with_throw_score(100)
        self.assertEqual(roster["blue_1"].throw, 100)
        self.assertEqual(roster["blue_1"].height, ROSTER["blue_1"].height)
        self.assertEqual(roster["red_5"].speed, ROSTER["red_5"].speed)

    def test_initial_observation_has_no_previous_frames(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        observation = simulator.observation_for("blue_3")
        self.assertEqual(observation["decision_request"]["player_id"], "blue_3")
        self.assertEqual(observation["previous_frames_exact"], [])
        self.assertFalse(observation["decision_request"]["you_have_disc"])
        self.assertEqual(observation["tactical_context"]["your_fixed_matchup"], "red_3")
        self.assertEqual(observation["tactical_context"]["your_receiver_defender_state"]["player_id"], "red_3")
        self.assertEqual(observation["tactical_context"]["your_current_role"], "offense_receiver")
        self.assertTrue(observation["tactical_context"]["your_team_has_possession"])
        self.assertEqual(observation["tactical_context"]["possession_team_attacking_direction_x"], 1)
        self.assertEqual(observation["tactical_context"]["defense_should_protect_end_zone"], {"x_min": 165, "x_max": 201})
        state = observation["current_state"]
        self.assertGreater(state["players"]["red_1"]["x"], state["players"]["blue_1"]["x"])
        self.assertEqual(state["stall"]["limit"], 5)
        self.assertEqual(state["stall"]["remaining"], 5)
        self.assertTrue(state["stall"]["active"])

    def test_defender_observation_has_explicit_marking_guidance(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        observation = simulator.observation_for("red_3")
        marking = observation["tactical_context"]["defensive_marking"]

        self.assertEqual(marking["matchup"], "blue_3")
        self.assertEqual(marking["distance_to_matchup"], 2.236)
        self.assertFalse(marking["inside_marking_radius"])
        self.assertEqual(marking["preferred_marking_side"], "right/downfield side of the matchup because this matchup attacks toward increasing x")
        self.assertEqual(marking["primary_mark_target"], {"x": 60, "y": 31})
        self.assertEqual(marking["recovery_target_this_frame"], {"x": 60, "y": 31})
        self.assertIn({"x": 59, "y": 32}, marking["recommended_targets"])

    def test_thrower_cannot_move_and_marked_hold_counts_stall(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        result = simulator.step({"blue_1": {"action": "move", "target": {"x": 54, "y": 37}}})
        self.assertEqual((simulator.state.players["blue_1"].x, simulator.state.players["blue_1"].y), (42, 37))
        self.assertEqual(simulator.state.stall_count, 1)
        stall_event = next(event for event in result.events if event["type"] == "stall_count")
        self.assertEqual(stall_event["remaining"], 4)

    def test_stall_five_turns_over_to_marker(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        for _ in range(5):
            simulator.step({})
        self.assertEqual(simulator.state.disc.holder, "red_1")
        self.assertEqual(simulator.state.possession_team, "red")
        self.assertEqual(simulator.state.stall_count, 0)

    def test_movement_collision_favors_faster_player(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={
                    "blue_3": (10, 10),
                    "blue_5": (12, 10),
                    "blue_2": (10, 12),
                }
            ),
            seed=7,
        )
        simulator.step(
            {
                "blue_3": {"action": "move", "target": {"x": 11, "y": 10}},
                "blue_5": {"action": "move", "target": {"x": 11, "y": 10}},
                "blue_2": {"action": "move", "target": {"x": 12, "y": 10}},
            }
        )
        self.assertEqual((simulator.state.players["blue_3"].x, simulator.state.players["blue_3"].y), (11, 10))
        self.assertEqual((simulator.state.players["blue_5"].x, simulator.state.players["blue_5"].y), (12, 10))
        self.assertEqual((simulator.state.players["blue_2"].x, simulator.state.players["blue_2"].y), (10, 12))

    def test_successful_offensive_catch(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={"blue_3": (60, 37), "red_3": (60, 45)},
                roster_updates={"blue_1": {"throw": 100}},
            ),
            seed=7,
        )
        simulator.rng = FixedRng([0.0, 0.0])
        result = signal_then_throw(
            simulator,
            {
                "action": "throw",
                "target": {"x": 60, "y": 37},
                "intended_receiver": "blue_3",
                "throw_side": "forehand",
                "disc_speed": 18,
            },
        )
        self.assertEqual(simulator.state.disc.holder, "blue_3")
        self.assertTrue(any(event["type"] == "catch" and event["player"] == "blue_3" for event in result.events))

    def test_defensive_candidate_with_greater_height_blocks(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={"blue_3": (60, 37), "red_5": (59, 37), "red_3": (60, 45)},
                roster_updates={"blue_1": {"throw": 100}},
            ),
            seed=7,
        )
        simulator.rng = FixedRng([0.0])
        result = signal_then_throw(
            simulator,
            {
                "action": "throw",
                "target": {"x": 60, "y": 37},
                "intended_receiver": "blue_3",
                "throw_side": "forehand",
                "disc_speed": 18,
            },
        )
        self.assertEqual(simulator.state.disc.holder, "red_5")
        self.assertEqual(simulator.state.possession_team, "red")
        self.assertTrue(any(event["type"] == "defensive_block" and event["player"] == "red_5" for event in result.events))

    def test_earlier_disc_contact_beats_later_taller_candidate(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={
                    "blue_1": (10, 10),
                    "blue_2": (20, 10),
                    "red_2": (5, 10),
                    "red_5": (35, 10),
                },
                roster_updates={"blue_1": {"throw": 100}},
            ),
            seed=7,
        )
        simulator.rng = FixedRng([0.0, 0.0])
        result = signal_then_throw(
            simulator,
            {
                "action": "throw",
                "target": {"x": 40, "y": 10},
                "intended_receiver": "blue_2",
                "throw_side": "forehand",
                "disc_speed": 30,
            },
        )
        self.assertEqual(simulator.state.disc.holder, "blue_2")
        self.assertTrue(any(event["type"] == "catch" and event["player"] == "blue_2" for event in result.events))

    def test_equal_height_disc_candidate_uses_random_draw(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={"blue_3": (59, 36), "red_3": (59, 38)},
                roster_updates={"blue_1": {"throw": 100}, "blue_3": {"height": 80}, "red_3": {"height": 80}},
            ),
            seed=7,
        )
        fixed_rng = FixedRng([0.0], choice_value="red_3")
        simulator.rng = fixed_rng
        signal_then_throw(
            simulator,
            {
                "action": "throw",
                "target": {"x": 60, "y": 37},
                "intended_receiver": "blue_3",
                "throw_side": "forehand",
                "disc_speed": 18,
            },
        )
        self.assertEqual(fixed_rng.choice_calls, 1)
        self.assertEqual(simulator.state.disc.holder, "red_3")

    def test_thrower_cannot_catch_own_flying_throw(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={
                    "blue_1": (10, 10),
                    "blue_2": (80, 30),
                    "blue_3": (80, 40),
                    "blue_4": (80, 50),
                    "blue_5": (80, 60),
                    "red_1": (90, 10),
                    "red_2": (5, 10),
                    "red_3": (90, 30),
                    "red_4": (90, 40),
                    "red_5": (90, 50),
                },
                roster_updates={"blue_1": {"throw": 100}},
            ),
            seed=7,
        )
        simulator.rng = FixedRng([0.0, 0.0, 0.0])
        simulator.step({"blue_1": {"action": "signal_throw", "intended_receiver": "blue_2"}})
        simulator.step(
            {
                "blue_1": {
                    "action": "throw",
                    "target": {"x": 40, "y": 10},
                    "intended_receiver": "blue_2",
                    "throw_side": "forehand",
                    "disc_speed": 10,
                }
            }
        )
        result = simulator.step({"blue_1": {"action": "move", "target": {"x": 20, "y": 10}}})

        self.assertIsNone(simulator.state.disc.holder)
        self.assertTrue(any(event["type"] == "disc_flying" for event in result.events))

    def test_player_cannot_catch_disc_at_old_position_after_moving_there(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(
                positions={
                    "blue_1": (90, 60),
                    "blue_2": (90, 10),
                    "blue_3": (90, 20),
                    "blue_4": (90, 30),
                    "blue_5": (90, 50),
                    "red_1": (45, 42),
                    "red_2": (90, 5),
                    "red_3": (90, 15),
                    "red_4": (90, 25),
                    "red_5": (90, 45),
                }
            ),
            seed=7,
        )
        for player in simulator.state.players.values():
            player.has_disc = False
        simulator.state.possession_team = "red"
        simulator.state.disc = DiscState(
            state="flying",
            holder=None,
            x=34,
            y=36,
            velocity_x=-8,
            velocity_y=0,
            last_throw={"thrower": "red_3", "intended_receiver": "red_1"},
        )

        result = simulator.step({"red_1": {"action": "move", "target": {"x": 27, "y": 36}}})

        self.assertIsNone(simulator.state.disc.holder)
        self.assertEqual((simulator.state.disc.x, simulator.state.disc.y), (26, 36))
        self.assertEqual((simulator.state.players["red_1"].x, simulator.state.players["red_1"].y), (34, 38))
        self.assertFalse(any(event["type"] == "catch" for event in result.events))
        self.assertTrue(any(event["type"] == "disc_flying" for event in result.events))

    def test_disc_out_of_bounds_is_turnover(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        simulator.state.players["blue_1"].has_disc = False
        simulator.state.disc = DiscState(state="flying", holder=None, x=200, y=10, velocity_x=10, velocity_y=0)
        result = simulator.step({})
        self.assertEqual(simulator.state.possession_team, "red")
        self.assertEqual(simulator.state.disc.state, "held")
        self.assertTrue(any(event["type"] == "disc_out_of_bounds" for event in result.events))

    def test_out_of_bounds_through_back_of_end_zone_restarts_in_central_zone(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        simulator.state.players["blue_1"].has_disc = False
        simulator.state.disc = DiscState(state="flying", holder=None, x=184.598, y=24.179, velocity_x=17.72, velocity_y=-3.164)
        result = simulator.step({})
        event = next(event for event in result.events if event["type"] == "disc_out_of_bounds")

        self.assertEqual(event["restart_spot"], {"x": 164, "y": 21})
        self.assertEqual(simulator.state.disc.holder, event["restart_player"])
        self.assertEqual(simulator.state.disc.x, 164)
        self.assertEqual(simulator.state.disc.y, 21)

    def test_flying_disc_observation_includes_future_path(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        simulator.state.players["blue_1"].has_disc = False
        simulator.state.disc = DiscState(state="flying", holder=None, x=50, y=20, velocity_x=6, velocity_y=2)
        disc = simulator.observation_for("blue_3")["current_state"]["disc"]

        self.assertEqual(disc["velocity"], {"x": 6, "y": 2})
        self.assertEqual(disc["speed"], 6.325)
        self.assertEqual(disc["future_path"][0], {"frame_offset": 1, "x": 56, "y": 22, "in_bounds": True})

    def test_observation_filters_private_pass_intent(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(roster_updates={"blue_1": {"throw": 100}}),
            seed=7,
        )
        simulator.rng = FixedRng([0.0])
        simulator.step(
            {
                "blue_1": {
                    "action": "throw",
                    "target": {"x": 80, "y": 37},
                    "intended_receiver": "blue_3",
                    "throw_side": "forehand",
                    "disc_speed": 5,
                }
            }
        )
        receiver_history = simulator.observation_for("blue_3")["previous_frames_exact"][0]
        unrelated_history = simulator.observation_for("blue_4")["previous_frames_exact"][0]

        self.assertFalse([event for event in receiver_history["public_events"] if event["type"] == "pass_intent"])
        self.assertFalse([event for event in unrelated_history["public_events"] if event["type"] == "pass_intent"])
        self.assertEqual(receiver_history["private_events_for_you"][0]["type"], "eye_contact")
        self.assertEqual(receiver_history["state"]["pending_pass"]["meaning"], "the thrower has committed to throw to you next frame")
        self.assertIsNone(unrelated_history["state"]["pending_pass"])

    def test_committed_pass_releases_next_frame(self) -> None:
        simulator = FrisbeeSimulator(
            config=custom_config(roster_updates={"blue_1": {"throw": 100}}),
            seed=7,
        )
        first = simulator.step(
            {
                "blue_1": {
                    "action": "signal_throw",
                    "intended_receiver": "blue_3",
                    "reason": "eye contact",
                }
            }
        )
        self.assertEqual(simulator.state.disc.holder, "blue_1")
        self.assertTrue(any(event["type"] == "pass_intent" for event in first.events))
        self.assertTrue(simulator.observation_for("blue_1")["legal_action_notes"]["must_throw_committed_pass"])

        second = simulator.step(
            {
                "blue_1": {
                    "action": "throw",
                    "target": {"x": 80, "y": 31},
                    "intended_receiver": "blue_3",
                    "throw_side": "forehand",
                    "disc_speed": 10,
                }
            }
        )
        self.assertTrue(any(event["type"] == "throw_released" for event in second.events))
        self.assertIsNone(simulator.state.pending_pass)

    def test_compact_history_omits_repeated_player_attributes(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        simulator.step({})
        history_state = simulator.observation_for("blue_3", compact_history=True)["previous_frames_exact"][0]["state"]
        self.assertIn("x", history_state["players"]["blue_1"])
        self.assertNotIn("height", history_state["players"]["blue_1"])

    def test_heuristic_policy_writes_jsonl_log(self) -> None:
        simulator = FrisbeeSimulator(seed=7)
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.jsonl"
            summary = simulator.run(HeuristicPolicy(), max_frames=3, log_path=log_path)
            events = [json.loads(line) for line in log_path.read_text().splitlines()]
        self.assertEqual(summary["frames"], 3)
        self.assertEqual(events[0]["type"], "episode_start")
        self.assertTrue(any(event["type"] == "frame" for event in events))
        self.assertEqual(events[-1]["type"], "episode_end")


if __name__ == "__main__":
    unittest.main()
