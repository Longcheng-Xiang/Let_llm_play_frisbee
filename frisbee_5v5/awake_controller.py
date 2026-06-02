from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .simulator import Action, FrisbeeSimulator, cell_dict, clip_target_to_speed


@dataclass
class PlayerIntent:
    player_id: str
    target: tuple[int, int]
    frames_remaining: int
    created_at_frame: int
    reason: str
    source: str = "model"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "move_intent",
            "player_id": self.player_id,
            "target": cell_dict(self.target),
            "frames_remaining": self.frames_remaining,
            "created_at_frame": self.created_at_frame,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class WakeDecision:
    awake_players: set[str]
    wake_reasons_by_player: dict[str, str]


class AwakeSleepController:
    def __init__(self) -> None:
        self.intents: dict[str, PlayerIntent] = {}
        self.wake_next: dict[str, str] = {}
        self.last_wake_reasons: dict[str, str] = {}
        self.last_action_sources: dict[str, str] = {}
        self.last_controller_actions: dict[str, dict[str, Any]] = {}
        self._intent_driven_players: set[str] = set()

    def decide_awake_players(self, simulator: FrisbeeSimulator) -> WakeDecision:
        reasons: dict[str, str] = {}
        player_ids = set(simulator.state.players)

        if simulator.state.frame == 0:
            reasons.update({player_id: "point_start" for player_id in player_ids})

        for player_id, reason in self.wake_next.items():
            if player_id in player_ids:
                reasons[player_id] = reason
        self.wake_next = {}

        holder = simulator.state.holder()
        if holder:
            reasons[holder] = "thrower"

        pending = simulator.state.pending_pass
        if pending:
            thrower = pending.get("thrower")
            receiver = pending.get("intended_receiver")
            if isinstance(thrower, str) and thrower in player_ids:
                reasons[thrower] = "committed_thrower"
            if isinstance(receiver, str) and receiver in player_ids:
                reasons[receiver] = "eye_contact_receiver"

        active_pair = self.active_disc_contest_pair(simulator)
        if active_pair:
            receiver, defender = active_pair
            reasons.setdefault(receiver, "active_disc_receiver")
            reasons.setdefault(defender, "active_disc_defender")

        for player_id in player_ids:
            player = simulator.state.players[player_id]
            if player.has_disc:
                continue
            if player_id in reasons:
                continue
            if not self._valid_intent(player_id):
                reasons[player_id] = "no_valid_intent"

        self.last_wake_reasons = dict(reasons)
        return WakeDecision(set(reasons), reasons)

    def augment_observation(
        self,
        simulator: FrisbeeSimulator,
        player_id: str,
        observation: dict[str, Any],
        decision: WakeDecision,
    ) -> dict[str, Any]:
        active_pair = self.active_disc_contest_pair(simulator)
        active_receiver = active_pair[0] if active_pair else None
        active_defender = active_pair[1] if active_pair else None
        player_ids = set(simulator.state.players)
        awake_players = sorted(decision.awake_players)
        sleeping_players = sorted(player_ids - decision.awake_players)
        player = simulator.state.players[player_id]
        must_throw = bool(observation.get("legal_action_notes", {}).get("must_throw_committed_pass"))
        active_contester = player_id in {active_receiver, active_defender}
        prefer_move_intent = not player.has_disc and not must_throw and not active_contester
        augmented = dict(observation)
        augmented["awake_context"] = {
            "version": "v2_awake_sleep",
            "wake_reason": decision.wake_reasons_by_player.get(player_id, "awake"),
            "awake_players": awake_players,
            "sleeping_players": sleeping_players,
            "prefer_move_intent": prefer_move_intent,
            "you_are_active_disc_contester": active_contester,
            "active_disc_intended_receiver": active_receiver,
            "active_disc_fixed_defender": active_defender,
            "disc_contest_rule": (
                "only intended receiver and their fixed defender may contest this flying disc"
                if active_pair
                else None
            ),
            "movement_intents": self.intent_board(simulator),
            "teammate_movement_intents": self.teammate_intent_board(simulator, player_id),
        }
        intent = self.intents.get(player_id)
        augmented["stored_intent_for_you"] = intent.as_dict() if intent else None
        return augmented

    def actions_for_frame(
        self,
        simulator: FrisbeeSimulator,
        model_actions: dict[str, Action],
        decision: WakeDecision,
    ) -> dict[str, Action]:
        actions: dict[str, Action] = {}
        self.last_action_sources = {}
        self.last_controller_actions = {}
        self._intent_driven_players = set()

        for player_id in simulator.state.players:
            if player_id in decision.awake_players:
                model_action = model_actions.get(player_id) or {"action": "hold", "reason": "No v2 model action."}
                actions[player_id] = self._action_for_awake_player(simulator, player_id, model_action)
            else:
                actions[player_id] = self._action_for_sleeping_player(simulator, player_id)

        return actions

    def update_after_frame(self, simulator: FrisbeeSimulator, frame_result: Any) -> None:
        eye_contact_receivers = {
            str(event.get("intended_receiver"))
            for event in frame_result.events
            if event.get("type") == "pass_intent" and isinstance(event.get("intended_receiver"), str)
        }
        blocked_players = self._players_with_blocked_movement(frame_result.events)
        for player_id in blocked_players:
            if self.last_action_sources.get(player_id) in {"controller", "move_intent"}:
                self.intents.pop(player_id, None)
                self.wake_next[player_id] = "movement_blocked"

        for player_id in list(self._intent_driven_players):
            if player_id in blocked_players:
                continue
            intent = self.intents.get(player_id)
            if intent is None:
                continue
            intent.frames_remaining -= 1
            player = simulator.state.players[player_id]
            if player_id in eye_contact_receivers:
                intent.frames_remaining = max(intent.frames_remaining, 1)
                continue
            if intent.frames_remaining <= 0:
                self.intents.pop(player_id, None)
                self.wake_next[player_id] = "intent_expired"

        self._wake_for_reset_events(simulator, frame_result.events)

    def active_disc_contest_pair(self, simulator: FrisbeeSimulator) -> tuple[str, str] | None:
        if simulator.state.disc.state != "flying":
            return None
        intended_receiver = (simulator.state.disc.last_throw or {}).get("intended_receiver")
        if not isinstance(intended_receiver, str) or intended_receiver not in simulator.state.players:
            return None
        return intended_receiver, simulator.matchup_for(intended_receiver)

    def snapshot(self) -> dict[str, Any]:
        return {
            "stored_intents": {player_id: intent.as_dict() for player_id, intent in sorted(self.intents.items())},
            "wake_reasons_by_player": dict(sorted(self.last_wake_reasons.items())),
            "action_sources": dict(sorted(self.last_action_sources.items())),
            "controller_actions": dict(sorted(self.last_controller_actions.items())),
        }

    def intent_board(self, simulator: FrisbeeSimulator) -> dict[str, Any]:
        return {
            player_id: self._intent_board_item(simulator, player_id)
            for player_id in sorted(simulator.state.players)
        }

    def teammate_intent_board(self, simulator: FrisbeeSimulator, player_id: str) -> list[dict[str, Any]]:
        player = simulator.state.players[player_id]
        teammates = [
            teammate_id
            for teammate_id, teammate in simulator.state.players.items()
            if teammate.team == player.team and teammate_id != player_id
        ]
        return [self._intent_board_item(simulator, teammate_id) for teammate_id in sorted(teammates)]

    def _action_for_awake_player(self, simulator: FrisbeeSimulator, player_id: str, action: Action) -> Action:
        if action.get("action") == "move_intent":
            intent = self._intent_from_action(simulator, player_id, action, source="model")
            if intent is None:
                self.intents.pop(player_id, None)
                self.wake_next[player_id] = "invalid_model_intent"
                self.last_action_sources[player_id] = "model"
                return {"action": "hold", "reason": "Invalid move_intent converted to hold."}
            self.intents[player_id] = intent
            move = self._move_from_intent(simulator, intent, source="move_intent")
            self._intent_driven_players.add(player_id)
            return move

        self.intents.pop(player_id, None)
        self.last_action_sources[player_id] = "model"
        return action

    def _action_for_sleeping_player(self, simulator: FrisbeeSimulator, player_id: str) -> Action:
        intent = self.intents.get(player_id)
        if intent is None or intent.frames_remaining <= 0:
            self.wake_next[player_id] = "no_valid_intent"
            self.last_action_sources[player_id] = "controller"
            action = {"action": "hold", "reason": "Sleeping player has no valid stored intent."}
            self.last_controller_actions[player_id] = action
            return action
        move = self._move_from_intent(simulator, intent, source="controller")
        self._intent_driven_players.add(player_id)
        return move

    def _intent_from_action(
        self,
        simulator: FrisbeeSimulator,
        player_id: str,
        action: Action,
        source: str,
    ) -> PlayerIntent | None:
        target = action.get("target")
        if not isinstance(target, dict):
            return None
        try:
            tx = float(target["x"])
            ty = float(target["y"])
        except (KeyError, TypeError, ValueError):
            return None
        duration = action.get("duration_frames", 4)
        try:
            frames = int(duration)
        except (TypeError, ValueError):
            frames = 4
        frames = min(max(frames, 1), 8)
        return PlayerIntent(
            player_id=player_id,
            target=simulator.config.field.clamp_cell(tx, ty),
            frames_remaining=frames,
            created_at_frame=simulator.state.frame,
            reason=str(action.get("reason", "Move toward stored v2 target."))[:240],
            source=source,
        )

    def _move_from_intent(self, simulator: FrisbeeSimulator, intent: PlayerIntent, source: str) -> Action:
        player = simulator.state.players[intent.player_id]
        target = clip_target_to_speed((player.x, player.y), intent.target, player.spec.max_move_cells)
        action = {
            "action": "move",
            "target": cell_dict(target),
            "reason": f"v2 {source}: {intent.reason}",
        }
        self.last_action_sources[intent.player_id] = source
        self.last_controller_actions[intent.player_id] = {
            **action,
            "intent_target": cell_dict(intent.target),
            "frames_remaining_before": intent.frames_remaining,
        }
        return action

    def _intent_board_item(self, simulator: FrisbeeSimulator, player_id: str) -> dict[str, Any]:
        player = simulator.state.players[player_id]
        intent = self.intents.get(player_id)
        base: dict[str, Any] = {
            "player_id": player_id,
            "current_position": {"x": player.x, "y": player.y},
            "max_move_cells": player.spec.max_move_cells,
        }
        if intent is None or intent.frames_remaining <= 0:
            base.update(
                {
                    "status": "no_intent",
                    "has_active_intent": False,
                    "safe_to_signal": False,
                }
            )
            return base
        planned_next = clip_target_to_speed((player.x, player.y), intent.target, player.spec.max_move_cells)
        expires_after_frame = simulator.state.frame + max(intent.frames_remaining, 0)
        base.update(
            {
                "status": self._intent_status(player, intent),
                "has_active_intent": True,
                "target": cell_dict(intent.target),
                "frames_remaining": intent.frames_remaining,
                "expires_after_frame": expires_after_frame,
                "planned_next_position": cell_dict(planned_next),
                "reason": intent.reason,
                "safe_to_signal": intent.frames_remaining >= 1,
            }
        )
        return base

    def _intent_status(self, player: Any, intent: PlayerIntent) -> str:
        if intent.frames_remaining <= 1:
            return "expires_this_frame"
        if (player.x, player.y) == intent.target:
            return "holding_at_target"
        return "active"

    def _wake_for_reset_events(self, simulator: FrisbeeSimulator, events: list[dict[str, Any]]) -> None:
        event_types = {event.get("type") for event in events}
        all_players = set(simulator.state.players)
        if simulator.state.stopped:
            for player_id in all_players:
                self.wake_next[player_id] = "game_stopped"
            return
        if "throw_released" in event_types and simulator.state.disc.state == "flying":
            for player_id in all_players:
                self.wake_next[player_id] = "first_flying_frame"
            return
        if event_types & {
            "catch",
            "defensive_block",
            "offensive_drop",
            "turnover",
            "disc_out_of_bounds",
            "throw_release_failed",
            "stall_turnover",
        }:
            self.intents.clear()
            for player_id in all_players:
                self.wake_next[player_id] = "disc_resolved"
            return
        if "pass_intent" in event_types and simulator.state.pending_pass:
            thrower = simulator.state.pending_pass.get("thrower")
            receiver = simulator.state.pending_pass.get("intended_receiver")
            if isinstance(thrower, str):
                self.wake_next[thrower] = "committed_thrower"
            if isinstance(receiver, str):
                self.wake_next[receiver] = "eye_contact_receiver"

    def _players_with_blocked_movement(self, events: list[dict[str, Any]]) -> set[str]:
        blocked: set[str] = set()
        for event in events:
            if event.get("type") in {"movement_blocked", "movement_lost_collision"}:
                player_id = event.get("player")
                if isinstance(player_id, str):
                    blocked.add(player_id)
        return blocked

    def _valid_intent(self, player_id: str) -> bool:
        intent = self.intents.get(player_id)
        return intent is not None and intent.frames_remaining > 0
