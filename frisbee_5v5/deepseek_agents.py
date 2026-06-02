from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import ROSTER, PlayerSpec
from .deepseek_probe import DEEPSEEK_PRICES_PER_MILLION, estimate_cost_usd


Action = dict[str, Any]


SYSTEM_PROMPT = """
You are controlling exactly one player in a 5v5 frisbee simulation.

Return only one compact JSON object. Do not return markdown. Do not narrate thoughts.
You control only the player named in the user message.
Your private reasoning is not visible to other players.
Public speech is heard by both teams.
Do not rely on outside frisbee knowledge; use this prompt as the game manual.

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
- There are no fixed handler/cutter roles in v1. The disc holder is the thrower; all teammates without the disc are receiving options.
- Only the disc holder can start or release a pass.
- A released throw aims at a coordinate.
- The target coordinate sets the flight direction; the disc does not stop or land at the target.
- The disc has a constant velocity vector after release. It does not curve, slow down, or change direction.
- When the disc is flying, the current observation includes velocity, speed, direction_unit, and future_path so you do not need to recompute the basic trajectory.
- A catch/block happens only when a player is within 2 cells of the flight segment after all players move for that frame.
- For controlled passes, choose a target and speed so the intended receiver can actually intersect the next flight segment. Do not aim far beyond a receiver unless they can run onto that line.
- Use maximum disc speed only for open deep throws. For short or medium throws, use a lower disc_speed close to the receiver distance.
- Avoid throwing through defenders who are within catch/block radius of the line from you to the receiver.
- Avoid throws whose straight-line trajectory will leave the field before the receiver can reach it. Near sidelines or end lines, aim flatter/in-bounds or reduce disc_speed.
- intended_receiver creates private eye contact only; it does not determine physics.
- If marked, forehand release succeeds 98 percent and backhand release succeeds 70 percent.
- If unmarked, forehand and backhand releases succeed 100 percent.
- Throw angular error uses sigma_deg = max(0, 18 * (100 - throw) / 100).
- If only offensive players are in disc radius, highest height offense attempts catch.
- If only defensive players are in disc radius, highest height defense causes turnover.
- If both teams are in disc radius, highest height player wins; exact height tie is random.
- If defense wins the disc, turnover is automatic.
- If offense wins the disc, catch probability is clamp(0.50 + height / 200, 0.55, 0.97).
- Offensive catch failure is a turnover.
- Out-of-bounds disc is a turnover.
- On an out-of-bounds turnover, play restarts at the central-zone cell nearest where the disc crossed out.
- Stall counts only when the thrower's fixed-matchup defender is within marking radius.
- Stall 5 is a turnover to the marker.

PASS TIMING
- Passing is a two-frame commitment in v1.
- If you hold the disc and no committed pass exists, choose `signal_throw` to establish private eye contact with one teammate. The disc stays in your hand for this frame.
- The intended receiver learns about that eye contact in their next prompt. Other players do not receive the private receiver identity.
- On the next frame, if you are still holding the disc, you must release the committed pass with `throw`.
- When releasing a committed pass, aim at the receiver's future space and choose disc_speed using the receiver's current position, speed, and likely cut.
- If you received eye contact, continue or adjust your cut so you can meet the thrower's likely next-frame flight path.
- If the disc is already flying, run toward the explicit future_path or defend that path.

TACTICAL BASICS
- Read `tactical_context` before choosing. It tells you whether your team currently has possession, your current role, your fixed matchup, and the current thrower.
- If you have `must_throw_committed_pass`, release the pass to `committed_receiver`.
- If you are `thrower` with no committed pass, choose the best teammate to receive private eye contact, or hold/talk if no teammate is plausible.
- If you are `offense_receiver`, create separation for the current thrower in your attacking direction, then react to eye contact if it appears.
- If you are `defender`, prioritize marking your fixed matchup. The current offense attacks in `possession_team_attacking_direction_x` toward `possession_team_attacking_end_zone`; protect that end zone and stay between your matchup and that scoring space.
- When marking, do not target the exact coordinate occupied by your matchup or the thrower. Choose an adjacent legal coordinate within marking radius, preferably goal-side or lane-side.
- If you are `you_are_current_thrower_marker`, get within marking radius of the current thrower to start the stall.
- After a turnover, switch roles immediately based on `your_team_has_possession`; do not keep playing offense for the old possession team.

ACTION SCHEMA
Return exactly one JSON object.

Move:
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


@dataclass(frozen=True)
class DeepSeekAgentConfig:
    api_key: str
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    timeout: float = 120.0
    max_tokens: int = 180
    thinking: str = "disabled"
    user_id: str | None = None

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


@dataclass
class ModelActionResult:
    player_id: str
    ok: bool
    latency_seconds: float
    action: Action
    status: int | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    raw_content: str | None = None
    reasoning_content: str | None = None
    finish_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "player_id": self.player_id,
            "ok": self.ok,
            "latency_seconds": round(self.latency_seconds, 3),
            "status": self.status,
            "action": self.action,
            "error": self.error,
            "usage": normalize_usage(self.usage or {}),
        }
        if self.finish_reason is not None:
            result["finish_reason"] = self.finish_reason
        if self.raw_content is not None:
            result["raw_content"] = self.raw_content
        if self.reasoning_content is not None:
            result["reasoning_content"] = self.reasoning_content
        return result


def stable_system_prompt(roster: dict[str, Any] | None = None, max_disc_speed: object = 30) -> str:
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
    return SYSTEM_PROMPT.format(roster_lines="\n".join(roster_lines), max_disc_speed=max_disc_speed)


def build_messages(player_id: str, observation: dict[str, Any]) -> list[dict[str, str]]:
    frame_packet = {
        "decision_request": {
            "player_id": player_id,
            "frame": observation["decision_request"]["frame"],
            "instruction": f"Choose exactly one legal action for {player_id} for this frame. Return only JSON.",
            "important": [
                f"You are {player_id} only.",
                "Use only this observation and the stable rules.",
                "Do not invent hidden memory.",
                "If legal_action_notes.must_throw_committed_pass is true, return a throw to that committed receiver.",
                "If no useful action is available, return hold.",
            ],
        },
        "current_state": observation["current_state"],
        "tactical_context": observation["tactical_context"],
        "previous_frames_exact": observation["previous_frames_exact"],
        "legal_action_notes": observation["legal_action_notes"],
        "output_requirements": {
            "must_return_json_only": True,
            "no_markdown": True,
            "no_explanation_outside_json": True,
        },
    }
    return [
        {
            "role": "system",
            "content": stable_system_prompt(
                observation.get("roster"),
                observation.get("constants", {}).get("max_disc_speed_cells_per_frame", 30),
            ),
        },
        {"role": "user", "content": json.dumps(frame_packet, sort_keys=True, separators=(",", ":"))},
    ]


def build_payload(config: DeepSeekAgentConfig, player_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": build_messages(player_id, observation),
        "stream": False,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
        "thinking": {"type": config.thinking},
    }
    if config.user_id:
        payload["user_id"] = config.user_id
    return payload


def call_player_action(config: DeepSeekAgentConfig, player_id: str, observation: dict[str, Any]) -> ModelActionResult:
    payload = build_payload(config, player_id, observation)
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
            action = parse_model_action(content)
            ok = action is not None
            return ModelActionResult(
                player_id=player_id,
                ok=ok,
                latency_seconds=latency,
                status=response.status,
                action=action or fallback_action("Response content was not a valid action."),
                error=None if ok else "Response content was not a valid action.",
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


def parse_model_action(content: str) -> Action | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    action = parsed.get("action")
    if action not in {"move", "signal_throw", "throw", "hold", "talk"}:
        return None
    reason = parsed.get("reason")
    if not isinstance(reason, str):
        parsed["reason"] = "No reason supplied."
    if action in {"move", "throw"}:
        target = parsed.get("target")
        if not valid_target(target):
            return None
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


def valid_target(target: object) -> bool:
    if not isinstance(target, dict):
        return False
    return isinstance(target.get("x"), int) and isinstance(target.get("y"), int)


def fallback_action(reason: str) -> Action:
    return {"action": "hold", "reason": f"Fallback hold: {reason}"}


def normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    normalized = {
        "prompt_tokens": int_value(usage.get("prompt_tokens")),
        "completion_tokens": int_value(usage.get("completion_tokens")),
        "total_tokens": int_value(usage.get("total_tokens")),
        "prompt_cache_hit_tokens": int_value(usage.get("prompt_cache_hit_tokens")),
        "prompt_cache_miss_tokens": int_value(usage.get("prompt_cache_miss_tokens")),
    }
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and not normalized["prompt_cache_hit_tokens"]:
        normalized["prompt_cache_hit_tokens"] = int_value(details.get("cached_tokens"))
    if normalized["prompt_tokens"] and not normalized["prompt_cache_miss_tokens"]:
        normalized["prompt_cache_miss_tokens"] = max(
            normalized["prompt_tokens"] - normalized["prompt_cache_hit_tokens"],
            0,
        )
    return normalized


def int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def sum_usage(results: list[ModelActionResult]) -> dict[str, int]:
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
    }
    for result in results:
        usage = normalize_usage(result.usage or {})
        for key in totals:
            totals[key] += usage[key]
    return totals


def estimate_usage_cost(model: str, usage: dict[str, int]) -> float | None:
    if model not in DEEPSEEK_PRICES_PER_MILLION:
        return None
    return estimate_cost_usd(model, usage)
