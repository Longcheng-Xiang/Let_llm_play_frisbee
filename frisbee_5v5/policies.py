from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import Team


Action = dict[str, Any]


class Policy(Protocol):
    name: str

    def choose_action(self, player_id: str, observation: dict[str, Any]) -> Action:
        """Return one JSON action for a single player observation."""


@dataclass
class HoldPolicy:
    name: str = "hold"

    def choose_action(self, player_id: str, observation: dict[str, Any]) -> Action:
        return {"action": "hold", "reason": "Offline hold policy."}


@dataclass
class HeuristicPolicy:
    name: str = "heuristic"

    def choose_action(self, player_id: str, observation: dict[str, Any]) -> Action:
        state = observation["current_state"]
        players = state["players"]
        player = players[player_id]
        team: Team = player["team"]
        possession_team: Team = state["possession_team"]
        disc = state["disc"]
        roster = observation["roster"]
        field = observation["field"]

        if player["has_disc"]:
            return self._throw_or_hold(player_id, observation)

        if disc["state"] == "flying":
            return self._move_toward_disc(player_id, observation)

        if team == possession_team:
            return self._offense_move(player_id, observation)

        matchup_id = paired_opponent(player_id, observation["fixed_matchups"])
        matchup = players[matchup_id]
        if matchup["has_disc"]:
            return {
                "action": "move",
                "target": marker_target_near_thrower(matchup, field),
                "reason": "Close down fixed matchup as marker.",
            }
        return {
            "action": "move",
            "target": adjacent_marking_target(player_id, matchup, roster, field),
            "reason": "Track fixed matchup on defense.",
        }

    def _throw_or_hold(self, player_id: str, observation: dict[str, Any]) -> Action:
        state = observation["current_state"]
        players = state["players"]
        team = players[player_id]["team"]
        field = observation["field"]
        direction = attack_direction(team)
        legal_notes = observation["legal_action_notes"]
        teammates = [
            (other_id, other)
            for other_id, other in players.items()
            if other["team"] == team and other_id != player_id
        ]
        if not teammates:
            return {"action": "hold", "reason": "No teammate exists."}

        committed_receiver = legal_notes.get("committed_receiver")
        if isinstance(committed_receiver, str) and committed_receiver in players:
            receiver_id = committed_receiver
            receiver = players[receiver_id]
        else:
            receiver_id, receiver = max(
                teammates,
                key=lambda item: (direction * item[1]["x"], item[1]["height"], item[0]),
            )
            return {
                "action": "signal_throw",
                "intended_receiver": receiver_id,
                "reason": f"Establish eye contact with {receiver_id} for the next-frame throw.",
            }

        lead = min(14, max(6, receiver["max_move_cells"]))
        target = {
            "x": clamp(round(receiver["x"] + direction * lead), 0, field["width"] - 1),
            "y": clamp(round(receiver["y"]), 0, field["height"] - 1),
        }
        return {
            "action": "throw",
            "target": target,
            "intended_receiver": receiver_id,
            "throw_side": "forehand",
            "disc_speed": 18,
            "reason": f"Lead {receiver_id} downfield with a forehand.",
        }

    def _move_toward_disc(self, player_id: str, observation: dict[str, Any]) -> Action:
        state = observation["current_state"]
        player = state["players"][player_id]
        disc = state["disc"]
        velocity = disc.get("velocity", {"x": 0, "y": 0})
        visible_receiver = (disc.get("last_throw") or {}).get("intended_receiver_visible_to_you")
        projection_frames = 1.0 if visible_receiver == player_id else 0.5
        target = {
            "x": round(disc["x"] + velocity.get("x", 0) * projection_frames),
            "y": round(disc["y"] + velocity.get("y", 0) * projection_frames),
        }
        return {
            "action": "move",
            "target": clamp_target(target, observation["field"]),
            "reason": "Move toward projected disc path.",
        }

    def _offense_move(self, player_id: str, observation: dict[str, Any]) -> Action:
        state = observation["current_state"]
        players = state["players"]
        player = players[player_id]
        disc = state["disc"]
        direction = attack_direction(player["team"])
        lane_y = lane_for_player(player_id, observation["field"]["height"])
        target = {
            "x": round(max(player["x"], disc["x"]) + direction * player["max_move_cells"]),
            "y": lane_y,
        }
        return {
            "action": "move",
            "target": clamp_target(target, observation["field"]),
            "reason": "Create downfield space for the thrower.",
        }


def policy_from_name(name: str) -> Policy:
    if name == "hold":
        return HoldPolicy()
    if name == "heuristic":
        return HeuristicPolicy()
    raise ValueError(f"Unknown offline policy {name!r}.")


def paired_opponent(player_id: str, matchups: dict[str, str]) -> str:
    if player_id in matchups:
        return matchups[player_id]
    for blue_id, red_id in matchups.items():
        if red_id == player_id:
            return blue_id
    raise KeyError(f"No fixed matchup for {player_id}.")


def attack_direction(team: Team) -> int:
    return 1 if team == "blue" else -1


def lane_for_player(player_id: str, field_height: int) -> int:
    lanes = {
        "1": 37,
        "2": 18,
        "3": 30,
        "4": 45,
        "5": 58,
    }
    suffix = player_id.rsplit("_", 1)[-1]
    return clamp(lanes.get(suffix, field_height // 2), 0, field_height - 1)


def marker_target_near_thrower(thrower: dict[str, Any], field: dict[str, Any]) -> dict[str, int]:
    direction = -attack_direction(thrower["team"])
    return clamp_target({"x": thrower["x"] + direction * 2, "y": thrower["y"]}, field)


def adjacent_marking_target(
    player_id: str,
    opponent: dict[str, Any],
    roster: dict[str, Any],
    field: dict[str, Any],
) -> dict[str, int]:
    marker_speed = roster[player_id]["speed"]
    side = 1 if marker_speed >= opponent["speed"] else -1
    return clamp_target({"x": opponent["x"] - attack_direction(opponent["team"]), "y": opponent["y"] + side}, field)


def clamp_target(target: dict[str, Any], field: dict[str, Any]) -> dict[str, int]:
    return {
        "x": clamp(round(float(target["x"])), 0, int(field["width"]) - 1),
        "y": clamp(round(float(target["y"])), 0, int(field["height"]) - 1),
    }


def clamp(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)
