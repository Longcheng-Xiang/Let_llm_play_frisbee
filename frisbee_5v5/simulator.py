from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import GameConfig, PlayerSpec, Team, matchup_for, other_team


Action = dict[str, Any]
CONTACT_PROGRESS_TOLERANCE = 0.08


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def as_dict(self) -> dict[str, float | int]:
        return {"x": clean_number(self.x), "y": clean_number(self.y)}


@dataclass
class PlayerState:
    spec: PlayerSpec
    x: int
    y: int
    has_disc: bool = False

    @property
    def player_id(self) -> str:
        return self.spec.player_id

    @property
    def team(self) -> Team:
        return self.spec.team

    def point(self) -> Point:
        return Point(self.x, self.y)

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "x": self.x,
            "y": self.y,
            "has_disc": self.has_disc,
            "height": self.spec.height,
            "speed": self.spec.speed,
            "throw": self.spec.throw,
            "captain": self.spec.captain,
            "max_move_cells": self.spec.max_move_cells,
        }


@dataclass
class DiscState:
    state: str
    x: float
    y: float
    holder: str | None = None
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    last_throw: dict[str, Any] | None = None

    def as_dict(
        self,
        observer_id: str | None = None,
        field: Any | None = None,
        future_frames: int = 5,
    ) -> dict[str, object]:
        data: dict[str, object] = {
            "state": self.state,
            "holder": self.holder,
            "x": clean_number(self.x),
            "y": clean_number(self.y),
        }
        if self.state == "flying":
            data["velocity"] = {
                "x": clean_number(self.velocity_x),
                "y": clean_number(self.velocity_y),
            }
            speed = math.hypot(self.velocity_x, self.velocity_y)
            data["speed"] = clean_number(speed)
            if speed:
                data["direction_unit"] = {
                    "x": clean_number(self.velocity_x / speed),
                    "y": clean_number(self.velocity_y / speed),
                }
            data["future_path"] = disc_future_path(self, field, future_frames)
        if self.last_throw:
            data["last_throw"] = filter_last_throw(self.last_throw, observer_id)
        return data


@dataclass
class GameState:
    frame: int
    players: dict[str, PlayerState]
    disc: DiscState
    possession_team: Team
    stall_count: int = 0
    stack_state: str = "none"
    stack_called_by: str | None = None
    stack_called_frame: int | None = None
    pending_pass: dict[str, Any] | None = None
    stopped: bool = False
    score_team: Team | None = None
    stop_reason: str | None = None

    def holder(self) -> str | None:
        return self.disc.holder if self.disc.state == "held" else None

    def as_dict(
        self,
        observer_id: str | None = None,
        matchups: dict[str, str] | None = None,
        field: Any | None = None,
        rules: Any | None = None,
    ) -> dict[str, object]:
        holder = self.holder()
        marker = matchup_for(holder, matchups) if holder else None
        stall_active = holder is not None
        if holder and marker and rules is not None:
            holder_player = self.players[holder]
            marker_player = self.players[marker]
            stall_active = (
                distance_between_cells((holder_player.x, holder_player.y), (marker_player.x, marker_player.y))
                <= rules.marking_radius_cells
            )
        stall_limit = rules.stall_limit if rules is not None else None
        stall_remaining = max(0, stall_limit - self.stall_count) if isinstance(stall_limit, int) else None
        return {
            "frame": self.frame,
            "possession_team": self.possession_team,
            "players": {player_id: player.as_dict() for player_id, player in self.players.items()},
            "disc": self.disc.as_dict(observer_id, field),
            "stall": {
                "count": self.stall_count,
                "limit": stall_limit,
                "remaining": stall_remaining,
                "thrower": holder,
                "marker": marker,
                "active": stall_active,
            },
            "stack": {
                "state": self.stack_state,
                "called_by": self.stack_called_by,
                "called_frame": self.stack_called_frame,
            },
            "pending_pass": filter_pending_pass(self.pending_pass, observer_id),
            "stopped": self.stopped,
            "score_team": self.score_team,
            "stop_reason": self.stop_reason,
        }


@dataclass
class FrameResult:
    frame_start: int
    frame_end: int
    actions: dict[str, Action]
    events: list[dict[str, Any]]
    state: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "type": "frame",
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
            "actions": self.actions,
            "events": self.events,
            "state": self.state,
        }


class FrisbeeSimulator:
    def __init__(self, config: GameConfig | None = None, seed: int | None = 7) -> None:
        self.config = config or GameConfig()
        self.rng = random.Random(seed)
        self.seed = seed
        self.state = self._initial_state()
        self.history: list[dict[str, object]] = []
        self._possession_changed_this_step = False

    def _initial_state(self) -> GameState:
        roster = self.config.resolved_roster()
        positions = self.config.resolved_initial_positions()
        players = {
            player_id: PlayerState(spec=spec, x=positions[player_id][0], y=positions[player_id][1])
            for player_id, spec in roster.items()
        }
        holder = self.config.initial_holder
        players[holder].has_disc = True
        hx, hy = players[holder].x, players[holder].y
        return GameState(
            frame=0,
            players=players,
            disc=DiscState(state="held", holder=holder, x=hx, y=hy),
            possession_team=self.config.initial_possession_team,
        )

    def matchup_for(self, player_id: str) -> str:
        return matchup_for(player_id, self.config.resolved_matchups())

    def snapshot(self, observer_id: str | None = None) -> dict[str, object]:
        return self.state.as_dict(observer_id, self.config.resolved_matchups(), self.config.field, self.config.rules)

    def observation_for(
        self,
        player_id: str,
        history_frames: int = 20,
        compact_history: bool = False,
    ) -> dict[str, object]:
        if player_id not in self.state.players:
            raise KeyError(f"Unknown player {player_id!r}.")
        player = self.state.players[player_id]
        holder = self.state.holder()
        matchups = self.config.resolved_matchups()
        player_matchup = matchup_for(player_id, matchups)
        recent_history = self.history[-history_frames:]
        previous = [
            filter_frame_for_player(frame, player_id, compact_state=compact_history)
            for frame in recent_history
        ]
        previous_public = [
            filter_frame_for_public(frame, compact_state=True)
            for frame in recent_history
        ]
        previous_private = [
            filter_private_frame_for_player(frame, player_id)
            for frame in recent_history
        ]
        tactical_context = {
            "your_player_id": player_id,
            "your_team_has_possession": player.team == self.state.possession_team,
            "your_current_role": role_for_player(player_id, player.team, holder, self.state.possession_team),
            "your_fixed_matchup": player_matchup,
            "your_fixed_matchup_state": self._player_tactical_summary(player_matchup),
            "your_receiver_defender_state": self._player_tactical_summary(player_matchup)
            if player.team == self.state.possession_team and not player.has_disc
            else None,
            "current_thrower": holder,
            "current_thrower_marker": matchup_for(holder, matchups) if holder else None,
            "you_are_current_thrower_marker": holder is not None and matchup_for(holder, matchups) == player_id,
            "your_attacking_direction_x": attack_direction(player.team),
            "your_attacking_end_zone": end_zone_dict(self.config.field.attacking_end_zone(player.team)),
            "possession_team_attacking_direction_x": attack_direction(self.state.possession_team),
            "possession_team_attacking_end_zone": end_zone_dict(
                self.config.field.attacking_end_zone(self.state.possession_team)
            ),
            "defense_should_protect_end_zone": end_zone_dict(
                self.config.field.attacking_end_zone(self.state.possession_team)
            ),
            "committed_pass_visible_to_you": filter_pending_pass(self.state.pending_pass, player_id),
            "you_have_committed_throw_to_release": self._has_committed_throw(player_id),
            "you_received_eye_contact": self._is_committed_receiver(player_id),
            "passing_options": self._passing_options(holder, matchups)
            if holder is not None and (player.has_disc or self._has_committed_throw(player_id))
            else [],
            "active_pass_context": self._active_pass_context(matchups),
            "defensive_marking": self._defensive_marking_guidance(player_id, player_matchup)
            if player.team != self.state.possession_team
            else None,
        }
        return {
            "decision_request": {
                "player_id": player_id,
                "frame": self.state.frame,
                "team": player.team,
                "you_have_disc": player.has_disc,
                "you_are_captain": player.spec.captain,
            },
            "field": {
                "width": self.config.field.width,
                "height": self.config.field.height,
                "cell_size_m": self.config.field.cell_size_m,
                "left_end_zone": {"x_min": 0, "x_max": self.config.field.left_end_zone_x_max},
                "right_end_zone": {
                    "x_min": self.config.field.right_end_zone_x_min,
                    "x_max": self.config.field.x_max,
                },
            },
            "constants": {
                "frame_duration_seconds": self.config.rules.frame_duration_seconds,
                "catch_block_radius_cells": self.config.rules.catch_block_radius_cells,
                "marking_radius_cells": self.config.rules.marking_radius_cells,
                "max_disc_speed_cells_per_frame": self.config.rules.max_disc_speed_cells_per_frame,
                "stall_limit": self.config.rules.stall_limit,
            },
            "roster": {pid: spec.as_dict() for pid, spec in self.config.resolved_roster().items()},
            "fixed_matchups": matchups,
            "tactical_context": tactical_context,
            "public_current_state": filter_state_for_player(self.snapshot(), PUBLIC_OBSERVER_ID, compact=True),
            "current_state": self.snapshot(observer_id=player_id),
            "previous_frames_public": previous_public,
            "previous_frames_private_for_you": previous_private,
            "previous_frames_exact": previous,
            "legal_action_notes": self.legal_action_notes(player_id),
        }

    def _player_tactical_summary(self, player_id: str | None) -> dict[str, object] | None:
        if player_id is None or player_id not in self.state.players:
            return None
        player = self.state.players[player_id]
        return {
            "player_id": player_id,
            "team": player.team,
            "position": {"x": player.x, "y": player.y},
            "max_move_cells": player.spec.max_move_cells,
            "speed": player.spec.speed,
            "height": player.spec.height,
            "has_disc": player.has_disc,
        }

    def _passing_options(self, holder_id: str, matchups: dict[str, str]) -> list[dict[str, object]]:
        holder = self.state.players[holder_id]
        holder_point = holder.point()
        options = []
        for receiver in sorted(self.state.players.values(), key=lambda player: player.player_id):
            if receiver.team != holder.team or receiver.player_id == holder_id:
                continue
            defender_id = matchup_for(receiver.player_id, matchups)
            defender = self.state.players[defender_id]
            receiver_point = receiver.point()
            defender_point = defender.point()
            lane_distance, lane_progress = point_to_segment_contact(defender_point, holder_point, receiver_point)
            options.append(
                {
                    "receiver": receiver.player_id,
                    "receiver_position": {"x": receiver.x, "y": receiver.y},
                    "receiver_max_move_cells": receiver.spec.max_move_cells,
                    "receiver_height": receiver.spec.height,
                    "fixed_defender": defender_id,
                    "defender_position": {"x": defender.x, "y": defender.y},
                    "defender_max_move_cells": defender.spec.max_move_cells,
                    "defender_height": defender.spec.height,
                    "defender_distance_to_receiver": clean_number(
                        distance_between_cells((defender.x, defender.y), (receiver.x, receiver.y))
                    ),
                    "defender_distance_to_current_lane": clean_number(lane_distance),
                    "defender_lane_progress": clean_number(lane_progress),
                    "current_lane_contested": lane_distance <= self.config.rules.catch_block_radius_cells,
                }
            )
        return options

    def _active_pass_context(self, matchups: dict[str, str]) -> dict[str, object] | None:
        receiver_id = None
        if self.state.pending_pass:
            receiver_id = self.state.pending_pass.get("intended_receiver")
        elif self.state.disc.state == "flying":
            receiver_id = (self.state.disc.last_throw or {}).get("intended_receiver")
        if not isinstance(receiver_id, str) or receiver_id not in self.state.players:
            return None
        defender_id = matchup_for(receiver_id, matchups)
        return {
            "intended_receiver": receiver_id,
            "receiver_state": self._player_tactical_summary(receiver_id),
            "fixed_defender": defender_id,
            "defender_state": self._player_tactical_summary(defender_id),
        }

    def _defensive_marking_guidance(self, defender_id: str, matchup_id: str | None) -> dict[str, object] | None:
        if matchup_id is None or matchup_id not in self.state.players or defender_id not in self.state.players:
            return None
        defender = self.state.players[defender_id]
        matchup = self.state.players[matchup_id]
        distance = distance_between_cells((defender.x, defender.y), (matchup.x, matchup.y))
        recommended_targets = self._marking_targets_near_matchup(matchup)
        primary = recommended_targets[0] if recommended_targets else {"x": matchup.x, "y": matchup.y}
        recovery = clip_target_to_speed(
            (defender.x, defender.y),
            (int(primary["x"]), int(primary["y"])),
            defender.spec.max_move_cells,
        )
        direction = attack_direction(matchup.team)
        if direction > 0:
            preferred_side = "right/downfield side of the matchup because this matchup attacks toward increasing x"
        else:
            preferred_side = "left/downfield side of the matchup because this matchup attacks toward decreasing x"
        return {
            "matchup": matchup_id,
            "matchup_position": {"x": matchup.x, "y": matchup.y},
            "distance_to_matchup": clean_number(distance),
            "inside_marking_radius": distance <= self.config.rules.marking_radius_cells,
            "marking_radius_cells": self.config.rules.marking_radius_cells,
            "matchup_attacking_direction_x": direction,
            "preferred_marking_side": preferred_side,
            "principle": "first stay close to fixed matchup; if choosing a side while close, prefer the matchup's attacking-end-zone side; never protect space by drifting far from the matchup",
            "primary_mark_target": primary,
            "recovery_target_this_frame": cell_dict(recovery),
            "recommended_targets": recommended_targets,
        }

    def _marking_targets_near_matchup(self, matchup: PlayerState) -> list[dict[str, int]]:
        direction = attack_direction(matchup.team)
        offsets = [
            (2 * direction, 0),
            (direction, 1),
            (direction, -1),
            (direction, 0),
            (0, 2),
            (0, -2),
            (-direction, 1),
            (-direction, -1),
        ]
        targets: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for dx, dy in offsets:
            candidate = self.config.field.clamp_cell(matchup.x + dx, matchup.y + dy)
            if candidate == (matchup.x, matchup.y) or candidate in seen:
                continue
            if distance_between_cells(candidate, (matchup.x, matchup.y)) > self.config.rules.marking_radius_cells:
                continue
            seen.add(candidate)
            targets.append(candidate)
        return [cell_dict(target) for target in targets]

    def legal_action_notes(self, player_id: str) -> dict[str, object]:
        player = self.state.players[player_id]
        has_committed_throw = self._has_committed_throw(player_id)
        can_start_pass = player.has_disc and self.state.pending_pass is None and not self.state.stopped
        return {
            "can_move": not player.has_disc and not self.state.stopped,
            "max_move_cells": player.spec.max_move_cells if not player.has_disc else 0,
            "can_signal_throw": can_start_pass,
            "can_throw": has_committed_throw and not self.state.stopped,
            "must_throw_committed_pass": has_committed_throw and not self.state.stopped,
            "committed_receiver": self.state.pending_pass.get("intended_receiver")
            if has_committed_throw and self.state.pending_pass
            else None,
            "can_call_stack": False,
            "can_talk": not self.state.stopped,
            "can_hold": not self.state.stopped,
        }

    def _has_committed_throw(self, player_id: str) -> bool:
        return bool(
            self.state.pending_pass
            and self.state.pending_pass.get("thrower") == player_id
            and self.state.holder() == player_id
        )

    def _is_committed_receiver(self, player_id: str) -> bool:
        return bool(self.state.pending_pass and self.state.pending_pass.get("intended_receiver") == player_id)

    def step(self, actions: dict[str, Action]) -> FrameResult:
        if self.state.stopped:
            return FrameResult(
                frame_start=self.state.frame,
                frame_end=self.state.frame,
                actions={},
                events=[{"type": "already_stopped", "reason": self.state.stop_reason}],
                state=self.snapshot(),
            )

        frame_start = self.state.frame
        events: list[dict[str, Any]] = []
        self._possession_changed_this_step = False
        normalized = self._normalize_actions(actions, events)
        movement_starts = {player_id: player.point() for player_id, player in self.state.players.items()}

        self._apply_public_actions(normalized, events)
        self._resolve_movement(normalized, events)
        ignored_for_disc = self._resolve_throw_release(normalized, events)
        self._advance_disc(events, ignored_for_disc, movement_starts)
        self._resolve_stall_if_still_held(events)

        self.state.frame += 1
        state_snapshot = self.snapshot()
        result = FrameResult(
            frame_start=frame_start,
            frame_end=self.state.frame,
            actions=normalized,
            events=events,
            state=state_snapshot,
        )
        self.history.append(result.as_dict())
        return result

    def run(
        self,
        policy: Any,
        max_frames: int = 60,
        log_path: str | Path | None = None,
    ) -> dict[str, object]:
        log_file = None
        path = Path(log_path) if log_path else None
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            log_file = path.open("w", encoding="utf-8")
        try:
            self._write_event(log_file, {"type": "episode_start", "seed": self.seed, "state": self.snapshot()})
            while not self.state.stopped and self.state.frame < max_frames:
                observations = {pid: self.observation_for(pid) for pid in self.state.players}
                actions = {pid: policy.choose_action(pid, observations[pid]) for pid in self.state.players}
                result = self.step(actions)
                self._write_event(log_file, result.as_dict())
            summary = {
                "type": "episode_end",
                "frames": self.state.frame,
                "stopped": self.state.stopped,
                "score_team": self.state.score_team,
                "stop_reason": self.state.stop_reason or "max_frames",
                "log_path": str(path) if path else None,
            }
            self._write_event(log_file, summary)
            return summary
        finally:
            if log_file:
                log_file.close()

    def _write_event(self, log_file: Any, event: dict[str, object]) -> None:
        if log_file is None:
            return
        log_file.write(json.dumps(event, sort_keys=True) + "\n")
        log_file.flush()

    def _normalize_actions(self, actions: dict[str, Action], events: list[dict[str, Any]]) -> dict[str, Action]:
        normalized: dict[str, Action] = {}
        for player_id in self.state.players:
            raw = actions.get(player_id) or {"action": "hold", "reason": "No action submitted."}
            if not isinstance(raw, dict):
                events.append({"type": "invalid_action", "player": player_id, "detail": "Action was not an object."})
                raw = {"action": "hold", "reason": "Invalid non-object action."}
            action_name = raw.get("action")
            if action_name not in {"move", "signal_throw", "throw", "hold", "call_stack", "talk"}:
                events.append({"type": "invalid_action", "player": player_id, "detail": f"Unknown action {action_name!r}."})
                raw = {"action": "hold", "reason": "Unknown action converted to hold."}
            normalized[player_id] = dict(raw)
        return normalized

    def _apply_public_actions(self, actions: dict[str, Action], events: list[dict[str, Any]]) -> None:
        for player_id, action in actions.items():
            player = self.state.players[player_id]
            if action["action"] == "talk":
                events.append(
                    {
                        "type": "public_message",
                        "player": player_id,
                        "message": str(action.get("message", ""))[:200],
                    }
                )
            if action["action"] != "call_stack":
                continue
            if not player.spec.captain or player.team != self.state.possession_team:
                events.append({"type": "illegal_call_stack", "player": player_id})
                continue
            self.state.stack_state = "forming"
            self.state.stack_called_by = player_id
            self.state.stack_called_frame = self.state.frame
            events.append(
                {
                    "type": "public_call",
                    "player": player_id,
                    "message": str(action.get("message", "stack"))[:200] or "stack",
                }
            )

    def _resolve_movement(self, actions: dict[str, Action], events: list[dict[str, Any]]) -> None:
        current_positions = {(player.x, player.y): player_id for player_id, player in self.state.players.items()}
        planned: dict[str, tuple[int, int]] = {}
        for player_id, player in self.state.players.items():
            action = actions[player_id]
            if player.has_disc or action["action"] != "move":
                planned[player_id] = (player.x, player.y)
                continue
            planned[player_id] = self._movement_target(player, action, events)

        empty_target_claims: dict[tuple[int, int], list[str]] = {}
        final_positions = {player_id: (player.x, player.y) for player_id, player in self.state.players.items()}
        for player_id, target in planned.items():
            current = final_positions[player_id]
            if target == current:
                continue
            occupant = current_positions.get(target)
            if occupant is not None:
                events.append({"type": "movement_blocked", "player": player_id, "target": cell_dict(target), "by": occupant})
                continue
            empty_target_claims.setdefault(target, []).append(player_id)

        for target, claimants in empty_target_claims.items():
            winner = sorted(claimants, key=lambda pid: (-self.state.players[pid].spec.speed, pid))[0]
            for player_id in claimants:
                if player_id == winner:
                    final_positions[player_id] = target
                    events.append({"type": "movement", "player": player_id, "to": cell_dict(target)})
                else:
                    events.append({"type": "movement_lost_collision", "player": player_id, "target": cell_dict(target), "winner": winner})

        for player_id, (x, y) in final_positions.items():
            player = self.state.players[player_id]
            player.x = x
            player.y = y
            if player.has_disc:
                self.state.disc.x = x
                self.state.disc.y = y

    def _movement_target(self, player: PlayerState, action: Action, events: list[dict[str, Any]]) -> tuple[int, int]:
        target = action.get("target")
        if not isinstance(target, dict):
            events.append({"type": "invalid_move", "player": player.player_id, "detail": "Missing target."})
            return player.x, player.y
        try:
            tx = float(target["x"])
            ty = float(target["y"])
        except (KeyError, TypeError, ValueError):
            events.append({"type": "invalid_move", "player": player.player_id, "detail": "Target needs x and y."})
            return player.x, player.y
        tx, ty = self.config.field.clamp_cell(tx, ty)
        return clip_target_to_speed((player.x, player.y), (tx, ty), player.spec.max_move_cells)

    def _resolve_throw_release(self, actions: dict[str, Action], events: list[dict[str, Any]]) -> set[str]:
        holder_id = self.state.holder()
        if holder_id is None:
            return set()
        action = actions[holder_id]

        if self._has_committed_throw(holder_id):
            if action["action"] != "throw":
                events.append(
                    {
                        "type": "committed_throw_forced",
                        "thrower": holder_id,
                        "intended_receiver": self.state.pending_pass.get("intended_receiver")
                        if self.state.pending_pass
                        else None,
                        "submitted_action": action.get("action"),
                    }
                )
                action = self._fallback_committed_throw_action(holder_id)
            return self._release_committed_throw(holder_id, action, events)

        if action["action"] == "signal_throw":
            self._create_pass_intent(holder_id, action, events)
            return set()

        if action["action"] != "throw":
            return set()

        self._create_pass_intent(holder_id, action, events)
        return set()

    def _create_pass_intent(self, holder_id: str, action: Action, events: list[dict[str, Any]]) -> None:
        holder = self.state.players[holder_id]
        intended_receiver = action.get("intended_receiver")
        if not isinstance(intended_receiver, str) or intended_receiver not in self.state.players:
            intended_receiver = self._default_receiver_for(holder_id)
        receiver = self.state.players[intended_receiver]
        if receiver.team != holder.team or receiver.player_id == holder_id:
            intended_receiver = self._default_receiver_for(holder_id)

        throw_side = str(action.get("throw_side", "forehand")).lower()
        if throw_side not in {"forehand", "backhand"}:
            throw_side = "forehand"

        self.state.pending_pass = {
            "created_frame": self.state.frame,
            "release_frame": self.state.frame + 1,
            "thrower": holder_id,
            "intended_receiver": intended_receiver,
            "target": safe_target_dict(action.get("target")),
            "throw_side": throw_side,
            "disc_speed": clean_number(
                parse_disc_speed(action.get("disc_speed"), self.config.rules.max_disc_speed_cells_per_frame)
            )
            if action.get("disc_speed") is not None
            else None,
            "rule": "must_release_next_frame",
        }
        events.append(
            {
                "type": "pass_intent",
                "thrower": holder_id,
                "intended_receiver": intended_receiver,
                "release_frame": self.state.frame + 1,
            }
        )

    def _default_receiver_for(self, holder_id: str) -> str:
        holder = self.state.players[holder_id]
        teammates = [
            player
            for player in self.state.players.values()
            if player.team == holder.team and player.player_id != holder_id
        ]
        direction = attack_direction(holder.team)
        return max(teammates, key=lambda player: (direction * player.x, player.spec.height, player.player_id)).player_id

    def _fallback_committed_throw_action(self, holder_id: str) -> Action:
        pending = self.state.pending_pass or {}
        receiver_id = str(pending.get("intended_receiver") or self._default_receiver_for(holder_id))
        receiver = self.state.players[receiver_id]
        holder = self.state.players[holder_id]
        direction = attack_direction(holder.team)
        lead = min(receiver.spec.max_move_cells, max(4, int(self.config.rules.max_disc_speed_cells_per_frame // 2)))
        target = self.config.field.clamp_cell(receiver.x + direction * lead, receiver.y)
        distance = math.hypot(target[0] - holder.x, target[1] - holder.y)
        speed = min(self.config.rules.max_disc_speed_cells_per_frame, max(6.0, distance))
        return {
            "action": "throw",
            "target": cell_dict(target),
            "intended_receiver": receiver_id,
            "throw_side": pending.get("throw_side") or "forehand",
            "disc_speed": pending.get("disc_speed") or clean_number(speed),
            "reason": "Forced release of committed eye-contact pass.",
        }

    def _release_committed_throw(self, holder_id: str, action: Action, events: list[dict[str, Any]]) -> set[str]:
        pending = self.state.pending_pass or {}
        action = dict(action)
        action["intended_receiver"] = pending.get("intended_receiver") or action.get("intended_receiver")

        holder = self.state.players[holder_id]
        target = action.get("target")
        if not isinstance(target, dict):
            events.append({"type": "invalid_throw", "player": holder_id, "detail": "Missing target; using committed fallback."})
            action = self._fallback_committed_throw_action(holder_id)
            target = action["target"]
        try:
            tx = float(target["x"])
            ty = float(target["y"])
        except (KeyError, TypeError, ValueError):
            events.append({"type": "invalid_throw", "player": holder_id, "detail": "Target needs x and y; using committed fallback."})
            action = self._fallback_committed_throw_action(holder_id)
            target = action["target"]
            tx = float(target["x"])
            ty = float(target["y"])
        tx, ty = self.config.field.clamp_cell(tx, ty)
        dx = tx - holder.x
        dy = ty - holder.y
        distance = math.hypot(dx, dy)
        if distance == 0:
            events.append({"type": "invalid_throw", "player": holder_id, "detail": "Target equals thrower position; using committed fallback."})
            action = self._fallback_committed_throw_action(holder_id)
            target = action["target"]
            tx = float(target["x"])
            ty = float(target["y"])
            dx = tx - holder.x
            dy = ty - holder.y
            distance = math.hypot(dx, dy)
            if distance == 0:
                return set()

        marker_id = self.matchup_for(holder_id)
        marker = self.state.players[marker_id]
        marked = distance_between_cells((holder.x, holder.y), (marker.x, marker.y)) <= self.config.rules.marking_radius_cells
        throw_side = str(action.get("throw_side", "forehand")).lower()
        release_probability = 1.0
        if marked:
            release_probability = 0.98 if throw_side == "forehand" else 0.70
        if self.rng.random() > release_probability:
            events.append(
                {
                    "type": "throw_release_failed",
                    "thrower": holder_id,
                    "marker": marker_id,
                    "throw_side": throw_side,
                    "release_probability": release_probability,
                }
            )
            self._turnover_to(marker_id, marker.x, marker.y, "marker_block", events)
            self.state.pending_pass = None
            return set()

        speed = parse_disc_speed(action.get("disc_speed"), self.config.rules.max_disc_speed_cells_per_frame)
        sigma_deg = max(0.0, 18.0 * (100 - holder.spec.throw) / 100)
        error_deg = self.rng.gauss(0.0, sigma_deg) if sigma_deg else 0.0
        angle = math.atan2(dy, dx) + math.radians(error_deg)
        vx = math.cos(angle) * speed
        vy = math.sin(angle) * speed

        holder.has_disc = False
        self.state.pending_pass = None
        self.state.disc = DiscState(
            state="flying",
            holder=None,
            x=holder.x,
            y=holder.y,
            velocity_x=vx,
            velocity_y=vy,
            last_throw={
                "released_frame": self.state.frame,
                "thrower": holder_id,
                "throw_side": throw_side,
                "disc_speed": clean_number(speed),
                "target": {"x": tx, "y": ty},
                "intended_receiver": action.get("intended_receiver"),
                "angle_error_degrees": clean_number(error_deg),
            },
        )
        self.state.stall_count = 0
        events.append(
            {
                "type": "throw_released",
                "thrower": holder_id,
                "throw_side": throw_side,
                "disc_speed": clean_number(speed),
                "target": {"x": tx, "y": ty},
                "intended_receiver": action.get("intended_receiver"),
                "marked": marked,
            }
        )
        ignored = {holder_id}
        if marked:
            ignored.add(marker_id)
        return ignored

    def _advance_disc(
        self,
        events: list[dict[str, Any]],
        ignored_players: set[str] | None = None,
        movement_starts: dict[str, Point] | None = None,
    ) -> None:
        ignored_players = ignored_players or set()
        if self.state.disc.state != "flying":
            return
        start = Point(self.state.disc.x, self.state.disc.y)
        end = Point(start.x + self.state.disc.velocity_x, start.y + self.state.disc.velocity_y)
        last_thrower = (self.state.disc.last_throw or {}).get("thrower")
        if isinstance(last_thrower, str):
            ignored_players.add(last_thrower)
        eligible_contesters = self._eligible_disc_contesters()
        candidates = []
        for player_id, player in self.state.players.items():
            if player_id in ignored_players:
                continue
            if eligible_contesters is not None and player_id not in eligible_contesters:
                continue
            player_start = movement_starts.get(player_id, player.point()) if movement_starts else player.point()
            distance, progress = moving_point_to_segment_contact(player_start, player.point(), start, end)
            if distance <= self.config.rules.catch_block_radius_cells:
                candidates.append({"player_id": player_id, "progress": progress, "distance": distance})
        if candidates:
            selected_id = self._select_disc_candidate(candidates)
            selected = next(candidate for candidate in candidates if candidate["player_id"] == selected_id)
            progress = float(selected["progress"])
            contact = Point(
                start.x + (end.x - start.x) * progress,
                start.y + (end.y - start.y) * progress,
            )
            self._resolve_disc_candidate(selected_id, end, events, contact, progress)
            return
        if not self.config.field.in_bounds(end.x, end.y):
            crossing = segment_field_exit_point(start, end, self.config.field) or Point(*self.config.field.nearest_in_bounds(end.x, end.y))
            restart_spot = self.config.field.nearest_central_zone_cell(crossing.x, crossing.y)
            gaining_team = other_team(self.state.possession_team)
            receiver_id = self._nearest_player_on_team(gaining_team, Point(*restart_spot))
            events.append(
                {
                    "type": "disc_out_of_bounds",
                    "at": end.as_dict(),
                    "crossing": crossing.as_dict(),
                    "restart_spot": cell_dict(restart_spot),
                    "restart_player": receiver_id,
                }
            )
            self._turnover_to(receiver_id, restart_spot[0], restart_spot[1], "out_of_bounds", events)
            return
        self.state.disc.x = end.x
        self.state.disc.y = end.y
        events.append({"type": "disc_flying", "from": start.as_dict(), "to": end.as_dict()})

    def _eligible_disc_contesters(self) -> set[str] | None:
        if not self.config.rules.restrict_disc_contest_to_intended_pair:
            return None
        intended_receiver = (self.state.disc.last_throw or {}).get("intended_receiver")
        if not isinstance(intended_receiver, str) or intended_receiver not in self.state.players:
            return None
        return {intended_receiver, self.matchup_for(intended_receiver)}

    def _select_disc_candidate(self, candidates: list[dict[str, Any]]) -> str:
        earliest = min(float(candidate["progress"]) for candidate in candidates)
        same_contact = [
            str(candidate["player_id"])
            for candidate in candidates
            if float(candidate["progress"]) <= earliest + CONTACT_PROGRESS_TOLERANCE
        ]
        max_height = max(self.state.players[player_id].spec.height for player_id in same_contact)
        tallest = [player_id for player_id in same_contact if self.state.players[player_id].spec.height == max_height]
        if len(tallest) == 1:
            return tallest[0]
        return self.rng.choice(sorted(tallest))

    def _resolve_disc_candidate(
        self,
        selected_id: str,
        segment_end: Point,
        events: list[dict[str, Any]],
        contact: Point,
        progress: float,
    ) -> None:
        selected = self.state.players[selected_id]
        contact_detail = {"at": contact.as_dict(), "progress": clean_number(progress)}
        if selected.team != self.state.possession_team:
            events.append({"type": "defensive_block", "player": selected_id, **contact_detail})
            self._turnover_to(selected_id, selected.x, selected.y, "defensive_block", events)
            return

        catch_probability = catch_probability_for_height(selected.spec.height)
        if self.rng.random() <= catch_probability:
            self._possession_to(selected_id, selected.x, selected.y)
            events.append(
                {
                    "type": "catch",
                    "player": selected_id,
                    "probability": clean_number(catch_probability),
                    **contact_detail,
                }
            )
            self._maybe_score(selected_id, events)
            return

        gaining_team = other_team(selected.team)
        receiver_id = self._nearest_player_on_team(gaining_team, segment_end)
        receiver = self.state.players[receiver_id]
        events.append(
            {
                "type": "offensive_drop",
                "player": selected_id,
                "probability": clean_number(catch_probability),
                "new_thrower": receiver_id,
                **contact_detail,
            }
        )
        self._turnover_to(receiver_id, receiver.x, receiver.y, "offensive_drop", events)

    def _resolve_stall_if_still_held(self, events: list[dict[str, Any]]) -> None:
        if self._possession_changed_this_step:
            return
        holder_id = self.state.holder()
        if holder_id is None or self.state.stopped:
            return
        holder = self.state.players[holder_id]
        marker_id = self.matchup_for(holder_id)
        marker = self.state.players[marker_id]
        if distance_between_cells((holder.x, holder.y), (marker.x, marker.y)) <= self.config.rules.marking_radius_cells:
            self.state.stall_count += 1
            remaining = max(0, self.config.rules.stall_limit - self.state.stall_count)
            events.append(
                {
                    "type": "stall_count",
                    "thrower": holder_id,
                    "marker": marker_id,
                    "count": self.state.stall_count,
                    "limit": self.config.rules.stall_limit,
                    "remaining": remaining,
                }
            )
        if self.state.stall_count >= self.config.rules.stall_limit:
            self._turnover_to(marker_id, marker.x, marker.y, "stall", events)
            events.append(
                {
                    "type": "stall_turnover",
                    "thrower": holder_id,
                    "marker": marker_id,
                    "limit": self.config.rules.stall_limit,
                }
            )

    def _turnover_to(self, player_id: str, x: int, y: int, reason: str, events: list[dict[str, Any]]) -> None:
        self._possession_to(player_id, x, y)
        self.state.possession_team = self.state.players[player_id].team
        self.state.stall_count = 0
        self.state.stack_state = "none"
        self.state.stack_called_by = None
        self.state.stack_called_frame = None
        self.state.pending_pass = None
        events.append({"type": "turnover", "reason": reason, "new_thrower": player_id})

    def _possession_to(self, player_id: str, x: int, y: int) -> None:
        for player in self.state.players.values():
            player.has_disc = False
        player = self.state.players[player_id]
        player.x = x
        player.y = y
        player.has_disc = True
        self.state.disc = DiscState(state="held", holder=player_id, x=x, y=y)
        self.state.possession_team = player.team
        self.state.pending_pass = None
        self._possession_changed_this_step = True

    def _maybe_score(self, player_id: str, events: list[dict[str, Any]]) -> None:
        player = self.state.players[player_id]
        if not self.config.field.is_score_cell(player.team, player.x):
            return
        events.append({"type": "score", "team": player.team, "player": player_id})
        if self.config.rules.stop_at_first_score:
            self.state.stopped = True
            self.state.score_team = player.team
            self.state.stop_reason = "score"

    def _nearest_player_on_team(self, team: Team, point: Point) -> str:
        candidates = [player for player in self.state.players.values() if player.team == team]
        selected = min(candidates, key=lambda player: (math.hypot(player.x - point.x, player.y - point.y), player.player_id))
        return selected.player_id


def clean_number(value: float) -> float | int:
    if isinstance(value, int):
        return value
    rounded = round(float(value), 3)
    if rounded.is_integer():
        return int(rounded)
    return rounded


def role_for_player(player_id: str, team: Team, holder: str | None, possession_team: Team) -> str:
    if holder == player_id:
        return "thrower"
    if team == possession_team:
        return "offense_receiver"
    return "defender"


def attack_direction(team: Team) -> int:
    return 1 if team == "blue" else -1


def end_zone_dict(end_zone: tuple[int, int]) -> dict[str, int]:
    return {"x_min": end_zone[0], "x_max": end_zone[1]}


def cell_dict(cell: tuple[int, int]) -> dict[str, int]:
    return {"x": cell[0], "y": cell[1]}


def safe_target_dict(target: object) -> dict[str, float] | None:
    if not isinstance(target, dict):
        return None
    try:
        return {"x": float(target["x"]), "y": float(target["y"])}
    except (KeyError, TypeError, ValueError):
        return None


def disc_future_path(disc: DiscState, field: Any | None = None, frames: int = 5) -> list[dict[str, object]]:
    path: list[dict[str, object]] = []
    for offset in range(1, max(0, frames) + 1):
        x = disc.x + disc.velocity_x * offset
        y = disc.y + disc.velocity_y * offset
        point: dict[str, object] = {
            "frame_offset": offset,
            "x": clean_number(x),
            "y": clean_number(y),
        }
        if field is not None:
            point["in_bounds"] = bool(field.in_bounds(x, y))
        path.append(point)
        if field is not None and not field.in_bounds(x, y):
            break
    return path


def segment_field_exit_point(start: Point, end: Point, field: Any) -> Point | None:
    dx = end.x - start.x
    dy = end.y - start.y
    candidates: list[float] = []
    if dx > 0 and end.x > field.x_max:
        candidates.append((field.x_max - start.x) / dx)
    if dx < 0 and end.x < 0:
        candidates.append((0 - start.x) / dx)
    if dy > 0 and end.y > field.y_max:
        candidates.append((field.y_max - start.y) / dy)
    if dy < 0 and end.y < 0:
        candidates.append((0 - start.y) / dy)
    valid = [value for value in candidates if 0 <= value <= 1]
    if not valid:
        return None
    t = min(valid)
    return Point(start.x + dx * t, start.y + dy * t)


def filter_pending_pass(pending_pass: dict[str, Any] | None, observer_id: str | None = None) -> dict[str, Any] | None:
    if pending_pass is None:
        return None
    if observer_id is None:
        return dict(pending_pass)
    if observer_id not in {pending_pass.get("thrower"), pending_pass.get("intended_receiver")}:
        return None
    filtered = {
        "created_frame": pending_pass.get("created_frame"),
        "release_frame": pending_pass.get("release_frame"),
        "thrower": pending_pass.get("thrower"),
        "rule": pending_pass.get("rule"),
    }
    if observer_id == pending_pass.get("thrower"):
        filtered["intended_receiver_visible_to_you"] = pending_pass.get("intended_receiver")
        filtered["you_must_release_next_frame"] = True
    if observer_id == pending_pass.get("intended_receiver"):
        filtered["you_received_eye_contact"] = True
        filtered["meaning"] = "the thrower has committed to throw to you next frame"
    return filtered


def filter_last_throw(last_throw: dict[str, Any], observer_id: str | None = None) -> dict[str, Any]:
    data = dict(last_throw)
    if observer_id is None:
        return data
    intended_receiver = data.pop("intended_receiver", None)
    if intended_receiver and observer_id in {intended_receiver, data.get("thrower")}:
        data["intended_receiver_visible_to_you"] = intended_receiver
    return data


PUBLIC_OBSERVER_ID = "__public__"


def filter_frame_for_player(
    frame: dict[str, object],
    player_id: str,
    compact_state: bool = False,
) -> dict[str, object]:
    raw_events = frame.get("events", [])
    events = [event for event in raw_events if isinstance(event, dict)] if isinstance(raw_events, list) else []
    actions = frame.get("actions", {})
    own_action = actions.get(player_id) if isinstance(actions, dict) else None
    return {
        "type": frame.get("type"),
        "frame_start": frame.get("frame_start"),
        "frame_end": frame.get("frame_end"),
        "state": filter_state_for_player(frame.get("state", {}), player_id, compact=compact_state),
        "public_events": [
            public_event
            for event in events
            if (public_event := filter_public_event(event, player_id)) is not None
        ],
        "private_events_for_you": private_events_for_player(events, player_id),
        "your_action": own_action,
    }


def filter_frame_for_public(frame: dict[str, object], compact_state: bool = True) -> dict[str, object]:
    raw_events = frame.get("events", [])
    events = [event for event in raw_events if isinstance(event, dict)] if isinstance(raw_events, list) else []
    return {
        "type": frame.get("type"),
        "frame_start": frame.get("frame_start"),
        "frame_end": frame.get("frame_end"),
        "state": filter_state_for_player(frame.get("state", {}), PUBLIC_OBSERVER_ID, compact=compact_state),
        "public_events": [
            public_event
            for event in events
            if (public_event := filter_public_event(event, PUBLIC_OBSERVER_ID)) is not None
        ],
    }


def filter_private_frame_for_player(frame: dict[str, object], player_id: str) -> dict[str, object]:
    raw_events = frame.get("events", [])
    events = [event for event in raw_events if isinstance(event, dict)] if isinstance(raw_events, list) else []
    actions = frame.get("actions", {})
    own_action = actions.get(player_id) if isinstance(actions, dict) else None
    return {
        "frame_start": frame.get("frame_start"),
        "frame_end": frame.get("frame_end"),
        "private_events_for_you": private_events_for_player(events, player_id),
        "your_action": own_action,
    }


def filter_state_for_player(state: object, player_id: str, compact: bool = False) -> dict[str, object]:
    if not isinstance(state, dict):
        return {}
    filtered = compact_history_state(state) if compact else dict(state)
    disc = filtered.get("disc")
    if isinstance(disc, dict):
        filtered_disc = dict(disc)
        last_throw = filtered_disc.get("last_throw")
        if isinstance(last_throw, dict):
            filtered_disc["last_throw"] = filter_last_throw(last_throw, player_id)
        filtered["disc"] = filtered_disc
    pending_pass = filtered.get("pending_pass")
    if isinstance(pending_pass, dict):
        filtered["pending_pass"] = filter_pending_pass(pending_pass, player_id)
    return filtered


def compact_history_state(state: dict[str, object]) -> dict[str, object]:
    players = state.get("players", {})
    compact_players: dict[str, object] = {}
    if isinstance(players, dict):
        for player_id, player in players.items():
            if not isinstance(player, dict):
                continue
            compact_players[str(player_id)] = {
                "team": player.get("team"),
                "x": player.get("x"),
                "y": player.get("y"),
                "has_disc": player.get("has_disc"),
            }
    return {
        "frame": state.get("frame"),
        "possession_team": state.get("possession_team"),
        "players": compact_players,
        "disc": state.get("disc"),
        "stall": state.get("stall"),
        "stack": state.get("stack"),
        "pending_pass": state.get("pending_pass"),
        "stopped": state.get("stopped"),
        "score_team": state.get("score_team"),
        "stop_reason": state.get("stop_reason"),
    }


def filter_public_event(event: dict[str, Any], player_id: str) -> dict[str, Any] | None:
    if event.get("type") == "pass_intent":
        return None
    if event.get("type") not in {"throw_released", "committed_throw_forced"}:
        return dict(event)
    filtered = dict(event)
    intended_receiver = filtered.pop("intended_receiver", None)
    if intended_receiver and player_id in {intended_receiver, filtered.get("thrower")}:
        filtered["intended_receiver_visible_to_you"] = intended_receiver
    return filtered


def private_events_for_player(events: list[dict[str, Any]], player_id: str) -> list[dict[str, Any]]:
    private_events: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "pass_intent" or event.get("intended_receiver") != player_id:
            continue
        private_events.append(
            {
                "type": "eye_contact",
                "from": event.get("thrower"),
                "release_frame": event.get("release_frame"),
                "meaning": "the thrower has committed to throw to you next frame",
            }
        )
    return private_events


def distance_between_cells(left: tuple[int, int], right: tuple[int, int]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def clip_target_to_speed(start: tuple[int, int], target: tuple[int, int], max_distance: int) -> tuple[int, int]:
    sx, sy = start
    tx, ty = target
    distance = math.hypot(tx - sx, ty - sy)
    if distance <= max_distance:
        return tx, ty
    scale = max_distance / distance
    candidate = (int(round(sx + (tx - sx) * scale)), int(round(sy + (ty - sy) * scale)))
    while math.hypot(candidate[0] - sx, candidate[1] - sy) > max_distance:
        candidate = (
            candidate[0] - sign(candidate[0] - sx),
            candidate[1] - sign(candidate[1] - sy),
        )
    return candidate


def sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def parse_disc_speed(value: object, maximum: float) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = maximum
    if speed <= 0:
        return maximum
    return min(speed, maximum)


def throw_sigma_degrees(throw_score: int) -> float:
    return max(0.0, 18.0 * (100 - throw_score) / 100)


def catch_probability_for_height(height: int) -> float:
    return min(max(0.50 + height / 200, 0.55), 0.97)


def point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    return point_to_segment_contact(point, start, end)[0]


def point_to_segment_contact(point: Point, start: Point, end: Point) -> tuple[float, float]:
    dx = end.x - start.x
    dy = end.y - start.y
    if dx == 0 and dy == 0:
        return math.hypot(point.x - start.x, point.y - start.y), 0.0
    t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy)
    t = min(max(t, 0.0), 1.0)
    closest_x = start.x + t * dx
    closest_y = start.y + t * dy
    return math.hypot(point.x - closest_x, point.y - closest_y), t


def moving_point_to_segment_contact(player_start: Point, player_end: Point, disc_start: Point, disc_end: Point) -> tuple[float, float]:
    relative_x = player_start.x - disc_start.x
    relative_y = player_start.y - disc_start.y
    relative_vx = (player_end.x - player_start.x) - (disc_end.x - disc_start.x)
    relative_vy = (player_end.y - player_start.y) - (disc_end.y - disc_start.y)
    if relative_vx == 0 and relative_vy == 0:
        return math.hypot(relative_x, relative_y), 0.0
    t = -((relative_x * relative_vx) + (relative_y * relative_vy)) / (
        (relative_vx * relative_vx) + (relative_vy * relative_vy)
    )
    t = min(max(t, 0.0), 1.0)
    closest_x = relative_x + relative_vx * t
    closest_y = relative_y + relative_vy * t
    return math.hypot(closest_x, closest_y), t
