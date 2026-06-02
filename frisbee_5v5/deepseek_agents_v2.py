from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.request
from typing import Any

from .config import ROSTER, PlayerSpec
from .deepseek_agents import (
    Action,
    DeepSeekAgentConfig,
    ModelActionResult,
    estimate_usage_cost,
    fallback_action,
    normalize_usage,
    sum_usage,
)


SYSTEM_PROMPT_V2 = """
You are controlling exactly one player in version 2 of a 5v5 frisbee simulation.

Return only one compact JSON object. Do not return markdown. Do not narrate thoughts.
You control only the player named in the user message.
Your private reasoning is not visible to other players.
Public speech is heard by both teams.
Do not rely on outside frisbee knowledge; use this prompt as the game manual.
Keep reason strings short and plain. Do not put quotation marks inside reason strings.

VERSION 2 AWAKE/SLEEP RULE
- The simulator still resolves all 10 players every frame.
- Only awake players receive this model prompt.
- Sleeping players are moved by a deterministic controller using their last stored move_intent.
- If you are awake and do not hold the disc, prefer a short move_intent unless you are actively reacting to a flying disc.
- A move_intent is a concrete target the controller can execute over several frames while you sleep.
- If you reach the target before duration_frames expires, the controller keeps you there until the intent expires.
- Simple fixed targets are best. Do not describe a conditional plan.

GAME CONSTANTS
- One frame equals one simulated second.
- Field size is 202 x 74 grid cells. Valid coordinates: 0 <= x <= 201, 0 <= y <= 73.
- Left end zone: x 0 through 36. Right end zone: x 165 through 201.
- Blue attacks +x. Red attacks -x.
- First score stops the simulation.
- Catch/block radius is 2 cells for every player.
- Marking radius is 2 cells for every player.
- Max disc speed is {max_disc_speed} cells per frame.
- Disc flight is straight line with no speed decay.
- All catch/block radius checks use Euclidean distance.

ATTRIBUTES
- height controls offensive catch probability and contested-disc winner.
- speed controls maximum movement distance per frame.
- throw controls angular throw uncertainty.
- throw = 100 means zero angular uncertainty.

SPEED MAPPING
- speed 1-20: max 6 cells/frame.
- speed 21-40: max 8 cells/frame.
- speed 41-60: max 10 cells/frame.
- speed 61-80: max 12 cells/frame.
- speed 81-100: max 14 cells/frame.

ROSTER
{roster_lines}

FIXED MATCHUPS
- blue_1 <-> red_1.
- blue_2 <-> red_2.
- blue_3 <-> red_3.
- blue_4 <-> red_4.
- blue_5 <-> red_5.
- Matchups never change during the point.

CORE RULES
- If you hold the disc, you cannot move.
- If you do not hold the disc, you may move up to your max movement budget.
- Two players cannot occupy the same coordinate.
- If multiple players try to enter the same empty coordinate, fastest speed wins; tied speed uses deterministic player id order.
- There are no fixed handler/cutter roles in v2. The disc holder is the thrower; all teammates without the disc are receiving options.
- Only the disc holder can start or release a pass.
- A released throw aims at a coordinate.
- The target coordinate sets the flight direction; the disc does not stop or land at the target.
- The disc has a constant velocity vector after release. It does not curve, slow down, or change direction.
- When the disc is flying, the current observation includes velocity, speed, direction_unit, and future_path so you do not need to recompute the basic trajectory.
- In v2, only the intended receiver may catch an offensive pass.
- In v2, only the intended receiver's fixed defender may block or intercept that pass.
- All other players see the disc flight publicly, but should reposition for the likely next phase.
- For controlled passes, choose a target and speed so the intended receiver can actually intersect the next flight segment.
- Use maximum disc speed only for open deep throws. For short or medium throws, use lower disc_speed close to receiver distance.
- Throwers must inspect tactical_context.passing_options before signal_throw or throw.
- Avoid throwing through the intended receiver's fixed defender if that defender can reach the line or catch point.
- Do not select a receiver just because they are open now; compare receiver movement, defender movement, defender distance to the lane, and defender height.
- If every receiver is covered or likely to be blocked, hold instead of forcing a turnover.
- Receivers must inspect tactical_context.your_receiver_defender_state and active_pass_context. Your fixed matchup is the only defender who can block your intended pass, so create separation from that defender before and during the catch.
- Avoid throws whose straight-line trajectory will leave the field before the receiver can reach it.
- If marked, forehand release succeeds 98 percent and backhand release succeeds 70 percent.
- If unmarked, forehand and backhand releases succeed 100 percent.
- Throw angular error uses sigma_deg = max(0, 18 * (100 - throw) / 100).
- Offensive catch probability is clamp(0.50 + height / 200, 0.55, 0.97).
- Offensive catch failure is a turnover.
- Out-of-bounds disc is a turnover.
- On an out-of-bounds turnover, play restarts at the central-zone cell nearest where the disc crossed out.
- Stall counts only when the thrower's fixed-matchup defender is within marking radius.
- Stall 5 is a turnover to the marker.
- current_state.stall.remaining is the countdown before stall turnover. At 0, the marker receives possession.

PASS TIMING
- Passing is a two-frame commitment in v2.
- If you hold the disc and no committed pass exists, you may choose hold, talk, or signal_throw.
- Choose signal_throw only when passing_options show a plausible safe receiver and catch path.
- If all receivers are covered, the lane is contested, or the receiver's fixed defender can contest the catch point, hold or talk while stall_remaining allows.
- signal_throw commits to a receiver, not to stale coordinates. The disc stays in your hand for that frame.
- The intended receiver learns about that eye contact in their next prompt.
- Other players do not receive the private receiver identity until the throw is publicly released.
- After choosing signal_throw, on the next frame, if you are still holding the disc, you must release the committed pass with throw.
- On the release frame, use the receiver's current position, current movement, and likely cut to choose the actual throw target and disc_speed.
- If you received eye contact, continue or adjust your cut so you can meet the thrower's next-frame flight path.
- If the disc is already flying and you are the intended receiver, run toward a reachable point on future_path.
- If the disc is already flying and you are the intended receiver's fixed defender, contest that receiver and the catch point.

TACTICAL BASICS
- Read awake_context first. It says why you are awake and whether you should produce a direct action or a move_intent.
- If you have must_throw_committed_pass, release the pass to committed_receiver.
- If you are thrower with no committed pass, choose neutrally among hold, talk, and signal_throw. Signal only after checking that teammate's fixed defender in passing_options.
- If you are an offensive player without the disc, create separation from your fixed defender in your attacking direction.
- If you are a defender, prioritize staying close to your fixed matchup. Use tactical_context.defensive_marking.distance_to_matchup and recommended_targets.
- Defending space is secondary to defending your fixed matchup. Do not drift far away just to stand nearer the end zone.
- When marking, do not target the exact coordinate occupied by your matchup or the thrower. Choose an adjacent legal coordinate within marking radius.
- If tactical_context.defensive_marking.inside_marking_radius is false, strongly prefer recovery_target_this_frame or another recommended target near your matchup.
- If you are the current thrower marker, get within marking radius of the current thrower to start the stall.
- After a turnover, switch roles immediately based on your_team_has_possession.

ACTION SCHEMA
Return exactly one JSON object.

Move intent for sleeping controller:
{{"action":"move_intent","target":{{"x":0,"y":0}},"duration_frames":4,"reason":"short private reason"}}

Direct one-frame move:
{{"action":"move","target":{{"x":0,"y":0}},"reason":"short private reason"}}

Signal private eye contact:
{{"action":"signal_throw","intended_receiver":"player id","reason":"short private reason"}}

Release committed throw:
{{"action":"throw","target":{{"x":0,"y":0}},"intended_receiver":"player id or null","throw_side":"forehand or backhand","disc_speed":{max_disc_speed},"reason":"short private reason"}}

Hold:
{{"action":"hold","reason":"short private reason"}}

Talk:
{{"action":"talk","message":"public message heard by both teams","reason":"short private reason"}}
""".strip()


def stable_system_prompt_v2(roster: dict[str, Any] | None = None, max_disc_speed: object = 30) -> str:
    roster_lines = []
    source: dict[str, Any] = roster or ROSTER
    for player_id, spec in source.items():
        if isinstance(spec, PlayerSpec):
            captain_value = spec.captain
            height = spec.height
            speed = spec.speed
            throw = spec.throw
        elif isinstance(spec, dict):
            captain_value = bool(spec.get("captain"))
            height = spec.get("height")
            speed = spec.get("speed")
            throw = spec.get("throw")
        else:
            continue
        captain = "yes" if captain_value else "no"
        roster_lines.append(
            f"- {player_id}: captain {captain}, height {height}, speed {speed}, throw {throw}."
        )
    return SYSTEM_PROMPT_V2.format(roster_lines="\n".join(roster_lines), max_disc_speed=max_disc_speed)


def preferred_action_style_v2(observation: dict[str, Any]) -> str:
    legal_notes = observation["legal_action_notes"]
    if legal_notes.get("must_throw_committed_pass"):
        return "throw"
    if legal_notes.get("can_signal_throw"):
        return "thrower_decision"
    if observation.get("awake_context", {}).get("you_are_active_disc_contester"):
        return "move"
    return "move_intent"


def important_instructions_v2(player_id: str, observation: dict[str, Any]) -> list[str]:
    legal_notes = observation["legal_action_notes"]
    tactical_context = observation["tactical_context"]
    important = [
        f"You are {player_id} only.",
        "Use only this observation and the stable rules.",
        "Do not invent hidden memory.",
        "If legal_action_notes.must_throw_committed_pass is true, return a throw to that committed receiver.",
        "If preferred_action_style is thrower_decision, choose neutrally among hold, talk, or signal_throw based on risk and current_state.stall.remaining.",
        "Do not treat signal_throw as mandatory; use it only when the receiver and lane look safe enough.",
        "If awake_context.prefer_move_intent is true, return move_intent instead of a one-frame move.",
    ]
    if legal_notes.get("can_signal_throw") or legal_notes.get("must_throw_committed_pass"):
        important.append(
            "Before choosing signal_throw or throw, inspect tactical_context.passing_options and avoid the receiver's fixed defender."
        )
    if tactical_context.get("you_received_eye_contact"):
        important.append(
            "You received eye contact: inspect tactical_context.your_receiver_defender_state and cut to a reachable point your defender cannot contest."
        )
    active_pass = tactical_context.get("active_pass_context") or {}
    if active_pass.get("intended_receiver") == player_id:
        important.append(
            "The disc is for you: use current_state.disc.future_path and active_pass_context.defender_state to beat your fixed defender to the catch point."
        )
    defensive_marking = tactical_context.get("defensive_marking") or {}
    if defensive_marking:
        if defensive_marking.get("inside_marking_radius") is False:
            important.append(
                "You are outside marking radius of your fixed matchup; prefer tactical_context.defensive_marking.recovery_target_this_frame or a recommended target near the matchup."
            )
        else:
            important.append(
                "You are marking your fixed matchup; keep within marking radius and only adjust side if you can stay close."
            )
    return important


def shared_awake_context(awake_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": awake_context.get("version"),
        "awake_players": awake_context.get("awake_players"),
        "sleeping_players": awake_context.get("sleeping_players"),
        "active_disc_intended_receiver": awake_context.get("active_disc_intended_receiver"),
        "active_disc_fixed_defender": awake_context.get("active_disc_fixed_defender"),
        "disc_contest_rule": awake_context.get("disc_contest_rule"),
        "movement_intents": awake_context.get("movement_intents"),
    }


def private_awake_context(awake_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "wake_reason": awake_context.get("wake_reason"),
        "prefer_move_intent": awake_context.get("prefer_move_intent"),
        "you_are_active_disc_contester": awake_context.get("you_are_active_disc_contester"),
        "teammate_movement_intents": awake_context.get("teammate_movement_intents"),
    }


def private_current_state_for_prompt(current_state: dict[str, Any]) -> dict[str, Any]:
    disc = current_state.get("disc")
    private_disc = None
    if isinstance(disc, dict):
        last_throw = disc.get("last_throw")
        if isinstance(last_throw, dict) and "intended_receiver_visible_to_you" in last_throw:
            private_disc = {
                "state": disc.get("state"),
                "last_throw": last_throw,
            }
    return {
        "pending_pass": current_state.get("pending_pass"),
        "disc_private": private_disc,
    }


def build_messages_v2(player_id: str, observation: dict[str, Any]) -> list[dict[str, str]]:
    legal_notes = observation["legal_action_notes"]
    tactical_context = observation["tactical_context"]
    awake_context = observation.get("awake_context", {})
    shared_frame_context = {
        "packet_type": "v2_shared_frame_context",
        "frame": observation["decision_request"]["frame"],
        "current_state": observation.get("public_current_state", observation["current_state"]),
        "previous_public_frames": observation.get("previous_frames_public", []),
        "awake_sleep": shared_awake_context(awake_context),
    }
    player_decision_context = {
        "packet_type": "v2_player_decision_context",
        "decision_request": {
            "player_id": player_id,
            "frame": observation["decision_request"]["frame"],
            "instruction": f"Choose exactly one legal v2 action for {player_id}. Return only JSON.",
            "preferred_action_style": preferred_action_style_v2(observation),
            "important": important_instructions_v2(player_id, observation),
        },
        "awake_context": private_awake_context(awake_context),
        "current_state_private_for_you": private_current_state_for_prompt(observation["current_state"]),
        "tactical_context": tactical_context,
        "stored_intent_for_you": observation.get("stored_intent_for_you"),
        "previous_private_frames_for_you": observation.get("previous_frames_private_for_you", []),
        "legal_action_notes": legal_notes,
        "output_requirements": {
            "must_return_json_only": True,
            "no_markdown": True,
            "no_explanation_outside_json": True,
        },
    }
    frame_packet = {
        "shared_frame_context": shared_frame_context,
        "player_decision_context": player_decision_context,
    }
    return [
        {
            "role": "system",
            "content": stable_system_prompt_v2(
                observation.get("roster"),
                observation.get("constants", {}).get("max_disc_speed_cells_per_frame", 30),
            ),
        },
        {"role": "user", "content": json.dumps(frame_packet, separators=(",", ":"))},
    ]


def build_payload_v2(config: DeepSeekAgentConfig, player_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": build_messages_v2(player_id, observation),
        "stream": False,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
        "thinking": {"type": config.thinking},
    }
    if config.user_id:
        payload["user_id"] = config.user_id
    return payload


def call_player_action_v2(config: DeepSeekAgentConfig, player_id: str, observation: dict[str, Any]) -> ModelActionResult:
    payload = build_payload_v2(config, player_id, observation)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        config.endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            raw = response.read().decode("utf-8")
            latency = time.monotonic() - started
            data = json.loads(raw)
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content") or ""
            action = parse_model_action_v2(content)
            ok = action is not None
            return ModelActionResult(
                player_id=player_id,
                ok=ok,
                latency_seconds=latency,
                status=response.status,
                action=action or fallback_action("Response content was not a valid v2 action."),
                error=None if ok else "Response content was not a valid v2 action.",
                usage=data.get("usage"),
                raw_content=content,
                reasoning_content=message.get("reasoning_content"),
                finish_reason=choice.get("finish_reason"),
            )
    except urllib.error.HTTPError as error:
        latency = time.monotonic() - started
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        return ModelActionResult(
            player_id=player_id,
            ok=False,
            latency_seconds=latency,
            status=error.code,
            action=fallback_action(f"HTTP {error.code}"),
            error=f"HTTP {error.code}: {detail}",
        )
    except Exception as error:  # noqa: BLE001 - model adapter should convert any failure to a safe hold.
        latency = time.monotonic() - started
        return ModelActionResult(
            player_id=player_id,
            ok=False,
            latency_seconds=latency,
            action=fallback_action("Request failed."),
            error=repr(error),
        )


def parse_model_action_v2(content: str) -> Action | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = parse_repairable_action(content)
    if not isinstance(parsed, dict):
        return None
    action = parsed.get("action")
    if action not in {"move_intent", "move", "signal_throw", "throw", "hold", "talk"}:
        return None
    reason = parsed.get("reason")
    if not isinstance(reason, str):
        parsed["reason"] = "No reason supplied."
    if action in {"move_intent", "move", "throw"}:
        target = parsed.get("target")
        normalized_target = normalize_grid_target(target)
        if normalized_target is None:
            return None
        parsed["target"] = normalized_target
    if action == "move_intent":
        parsed["duration_frames"] = bounded_duration(parsed.get("duration_frames"))
    if action == "signal_throw" and not isinstance(parsed.get("intended_receiver"), str):
        parsed["intended_receiver"] = None
    if action == "throw":
        if parsed.get("throw_side") not in {"forehand", "backhand"}:
            parsed["throw_side"] = "forehand"
        if not isinstance(parsed.get("disc_speed"), (int, float)):
            parsed["disc_speed"] = 30
        if "intended_receiver" not in parsed:
            parsed["intended_receiver"] = None
    if action == "talk" and not isinstance(parsed.get("message"), str):
        parsed["message"] = ""
    return parsed


def normalize_grid_target(target: object) -> dict[str, int] | None:
    if not isinstance(target, dict):
        return None
    normalized: dict[str, int] = {}
    for axis in ("x", "y"):
        value = target.get(axis)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        normalized[axis] = int(round(numeric))
    return normalized


def parse_repairable_action(content: str) -> Action | None:
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(content.strip())
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    action_match = re.search(r'"action"\s*:\s*"([^"]+)"', content)
    if not action_match:
        return None
    action = action_match.group(1)
    if action not in {"move_intent", "move", "signal_throw", "throw", "hold", "talk"}:
        return None
    repaired: Action = {"action": action, "reason": "Repaired malformed JSON action."}

    target_match = re.search(r'"target"\s*:\s*\{\s*"x"\s*:\s*(-?\d+)\s*,\s*"y"\s*:\s*(-?\d+)', content)
    if target_match:
        repaired["target"] = {"x": int(target_match.group(1)), "y": int(target_match.group(2))}

    duration_match = re.search(r'"duration_frames"\s*:\s*(\d+)', content)
    if duration_match:
        repaired["duration_frames"] = int(duration_match.group(1))

    receiver_match = re.search(r'"intended_receiver"\s*:\s*"([^"]+)"', content)
    if receiver_match:
        repaired["intended_receiver"] = receiver_match.group(1)

    side_match = re.search(r'"throw_side"\s*:\s*"(forehand|backhand)"', content)
    if side_match:
        repaired["throw_side"] = side_match.group(1)

    speed_match = re.search(r'"disc_speed"\s*:\s*(-?\d+(?:\.\d+)?)', content)
    if speed_match:
        repaired["disc_speed"] = float(speed_match.group(1))

    message_match = re.search(r'"message"\s*:\s*"([^"]*)"', content)
    if message_match:
        repaired["message"] = message_match.group(1)

    return repaired


def bounded_duration(value: object) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        duration = 4
    return min(max(duration, 1), 8)


__all__ = [
    "DeepSeekAgentConfig",
    "ModelActionResult",
    "build_payload_v2",
    "call_player_action_v2",
    "estimate_usage_cost",
    "normalize_usage",
    "parse_model_action_v2",
    "stable_system_prompt_v2",
    "sum_usage",
]
