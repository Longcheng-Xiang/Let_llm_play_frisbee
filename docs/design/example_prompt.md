# Example V2 Prompt

This page shows one complete prompt packet from the current V2 awake/sleep system. It is meant for readers who want to understand what an individual agent actually receives before choosing an action.

The example is `blue_1` at frame `0` with the recommended default setup: V2 awake/sleep, DeepSeek V4 Flash, thinking enabled, throw score `100`, max disc speed `18`, seed `7`, and history window `4`. `blue_1` starts with the disc, so this is the first thrower decision of the point.

No API key, HTTP Authorization header, local file path, or user-private value is included here. The real request would add the API key only as an HTTP header outside this prompt body.

## How To Read This

- `request options` are the non-secret model settings sent with the request body.
- `system message` is the stable game manual. It changes rarely and is structured to be friendly to DeepSeek provider-side prompt caching.
- `user message` is the frame-specific JSON packet for one awake player. It changes every frame and differs for each player.
- `shared_frame_context` is public information: current state, recent public history, and awake/sleep state.
- `player_decision_context` is private to this player: identity, legal actions, tactical notes, stored intent, private events, and output rules.
- The model is expected to return one compact JSON action, not prose.

## Request Options

```json
{
  "model": "deepseek-v4-flash",
  "stream": false,
  "max_tokens": 8000,
  "response_format": {
    "type": "json_object"
  },
  "thinking": {
    "type": "enabled"
  }
}
```

## System Message

```text
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
- Max disc speed is 18.0 cells per frame.
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
- blue_1: captain yes, height 58, speed 63, throw 100.
- blue_2: captain no, height 82, speed 71, throw 100.
- blue_3: captain no, height 74, speed 86, throw 100.
- blue_4: captain no, height 66, speed 78, throw 100.
- blue_5: captain no, height 91, speed 55, throw 100.
- red_1: captain yes, height 61, speed 68, throw 100.
- red_2: captain no, height 77, speed 74, throw 100.
- red_3: captain no, height 69, speed 91, throw 100.
- red_4: captain no, height 73, speed 72, throw 100.
- red_5: captain no, height 94, speed 50, throw 100.

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
{"action":"move_intent","target":{"x":0,"y":0},"duration_frames":4,"reason":"short private reason"}

Direct one-frame move:
{"action":"move","target":{"x":0,"y":0},"reason":"short private reason"}

Signal private eye contact:
{"action":"signal_throw","intended_receiver":"player id","reason":"short private reason"}

Release committed throw:
{"action":"throw","target":{"x":0,"y":0},"intended_receiver":"player id or null","throw_side":"forehand or backhand","disc_speed":18.0,"reason":"short private reason"}

Hold:
{"action":"hold","reason":"short private reason"}

Talk:
{"action":"talk","message":"public message heard by both teams","reason":"short private reason"}
```

## User Message

The actual request sends this JSON compactly. It is pretty-printed here so humans can read it.

```json
{
  "player_decision_context": {
    "awake_context": {
      "prefer_move_intent": false,
      "teammate_movement_intents": [
        {
          "current_position": {
            "x": 54,
            "y": 18
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "blue_2",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        {
          "current_position": {
            "x": 58,
            "y": 31
          },
          "has_active_intent": false,
          "max_move_cells": 14,
          "player_id": "blue_3",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        {
          "current_position": {
            "x": 56,
            "y": 47
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "blue_4",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        {
          "current_position": {
            "x": 52,
            "y": 59
          },
          "has_active_intent": false,
          "max_move_cells": 10,
          "player_id": "blue_5",
          "safe_to_signal": false,
          "status": "no_intent"
        }
      ],
      "wake_reason": "thrower",
      "you_are_active_disc_contester": false
    },
    "current_state_private_for_you": {
      "disc_private": null,
      "pending_pass": null
    },
    "decision_request": {
      "frame": 0,
      "important": [
        "You are blue_1 only.",
        "Use only this observation and the stable rules.",
        "Do not invent hidden memory.",
        "If legal_action_notes.must_throw_committed_pass is true, return a throw to that committed receiver.",
        "If preferred_action_style is thrower_decision, choose neutrally among hold, talk, or signal_throw based on risk and current_state.stall.remaining.",
        "Do not treat signal_throw as mandatory; use it only when the receiver and lane look safe enough.",
        "If awake_context.prefer_move_intent is true, return move_intent instead of a one-frame move.",
        "Before choosing signal_throw or throw, inspect tactical_context.passing_options and avoid the receiver's fixed defender."
      ],
      "instruction": "Choose exactly one legal v2 action for blue_1. Return only JSON.",
      "player_id": "blue_1",
      "preferred_action_style": "thrower_decision"
    },
    "legal_action_notes": {
      "can_call_stack": false,
      "can_hold": true,
      "can_move": false,
      "can_signal_throw": true,
      "can_talk": true,
      "can_throw": false,
      "committed_receiver": null,
      "max_move_cells": 0,
      "must_throw_committed_pass": false
    },
    "output_requirements": {
      "must_return_json_only": true,
      "no_explanation_outside_json": true,
      "no_markdown": true
    },
    "packet_type": "v2_player_decision_context",
    "previous_private_frames_for_you": [],
    "stored_intent_for_you": null,
    "tactical_context": {
      "active_pass_context": null,
      "committed_pass_visible_to_you": null,
      "current_thrower": "blue_1",
      "current_thrower_marker": "red_1",
      "defense_should_protect_end_zone": {
        "x_max": 201,
        "x_min": 165
      },
      "defensive_marking": null,
      "passing_options": [
        {
          "current_lane_contested": true,
          "defender_distance_to_current_lane": 0.222,
          "defender_distance_to_receiver": 2.236,
          "defender_height": 77,
          "defender_lane_progress": 0.901,
          "defender_max_move_cells": 12,
          "defender_position": {
            "x": 53,
            "y": 20
          },
          "fixed_defender": "red_2",
          "receiver": "blue_2",
          "receiver_height": 82,
          "receiver_max_move_cells": 12,
          "receiver_position": {
            "x": 54,
            "y": 18
          }
        },
        {
          "current_lane_contested": true,
          "defender_distance_to_current_lane": 1.522,
          "defender_distance_to_receiver": 2.236,
          "defender_height": 69,
          "defender_lane_progress": 0.904,
          "defender_max_move_cells": 14,
          "defender_position": {
            "x": 57,
            "y": 33
          },
          "fixed_defender": "red_3",
          "receiver": "blue_3",
          "receiver_height": 74,
          "receiver_max_move_cells": 14,
          "receiver_position": {
            "x": 58,
            "y": 31
          }
        },
        {
          "current_lane_contested": false,
          "defender_distance_to_current_lane": 2.236,
          "defender_distance_to_receiver": 2.236,
          "defender_height": 73,
          "defender_lane_progress": 1,
          "defender_max_move_cells": 12,
          "defender_position": {
            "x": 55,
            "y": 49
          },
          "fixed_defender": "red_4",
          "receiver": "blue_4",
          "receiver_height": 66,
          "receiver_max_move_cells": 12,
          "receiver_position": {
            "x": 56,
            "y": 47
          }
        },
        {
          "current_lane_contested": false,
          "defender_distance_to_current_lane": 2.236,
          "defender_distance_to_receiver": 2.236,
          "defender_height": 94,
          "defender_lane_progress": 1,
          "defender_max_move_cells": 10,
          "defender_position": {
            "x": 51,
            "y": 61
          },
          "fixed_defender": "red_5",
          "receiver": "blue_5",
          "receiver_height": 91,
          "receiver_max_move_cells": 10,
          "receiver_position": {
            "x": 52,
            "y": 59
          }
        }
      ],
      "possession_team_attacking_direction_x": 1,
      "possession_team_attacking_end_zone": {
        "x_max": 201,
        "x_min": 165
      },
      "you_are_current_thrower_marker": false,
      "you_have_committed_throw_to_release": false,
      "you_received_eye_contact": false,
      "your_attacking_direction_x": 1,
      "your_attacking_end_zone": {
        "x_max": 201,
        "x_min": 165
      },
      "your_current_role": "thrower",
      "your_fixed_matchup": "red_1",
      "your_fixed_matchup_state": {
        "has_disc": false,
        "height": 61,
        "max_move_cells": 12,
        "player_id": "red_1",
        "position": {
          "x": 44,
          "y": 37
        },
        "speed": 68,
        "team": "red"
      },
      "your_player_id": "blue_1",
      "your_receiver_defender_state": null,
      "your_team_has_possession": true
    }
  },
  "shared_frame_context": {
    "awake_sleep": {
      "active_disc_fixed_defender": null,
      "active_disc_intended_receiver": null,
      "awake_players": [
        "blue_1",
        "blue_2",
        "blue_3",
        "blue_4",
        "blue_5",
        "red_1",
        "red_2",
        "red_3",
        "red_4",
        "red_5"
      ],
      "disc_contest_rule": null,
      "movement_intents": {
        "blue_1": {
          "current_position": {
            "x": 42,
            "y": 37
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "blue_1",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "blue_2": {
          "current_position": {
            "x": 54,
            "y": 18
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "blue_2",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "blue_3": {
          "current_position": {
            "x": 58,
            "y": 31
          },
          "has_active_intent": false,
          "max_move_cells": 14,
          "player_id": "blue_3",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "blue_4": {
          "current_position": {
            "x": 56,
            "y": 47
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "blue_4",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "blue_5": {
          "current_position": {
            "x": 52,
            "y": 59
          },
          "has_active_intent": false,
          "max_move_cells": 10,
          "player_id": "blue_5",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "red_1": {
          "current_position": {
            "x": 44,
            "y": 37
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "red_1",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "red_2": {
          "current_position": {
            "x": 53,
            "y": 20
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "red_2",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "red_3": {
          "current_position": {
            "x": 57,
            "y": 33
          },
          "has_active_intent": false,
          "max_move_cells": 14,
          "player_id": "red_3",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "red_4": {
          "current_position": {
            "x": 55,
            "y": 49
          },
          "has_active_intent": false,
          "max_move_cells": 12,
          "player_id": "red_4",
          "safe_to_signal": false,
          "status": "no_intent"
        },
        "red_5": {
          "current_position": {
            "x": 51,
            "y": 61
          },
          "has_active_intent": false,
          "max_move_cells": 10,
          "player_id": "red_5",
          "safe_to_signal": false,
          "status": "no_intent"
        }
      },
      "sleeping_players": [],
      "version": "v2_awake_sleep"
    },
    "current_state": {
      "disc": {
        "holder": "blue_1",
        "state": "held",
        "x": 42,
        "y": 37
      },
      "frame": 0,
      "pending_pass": null,
      "players": {
        "blue_1": {
          "has_disc": true,
          "team": "blue",
          "x": 42,
          "y": 37
        },
        "blue_2": {
          "has_disc": false,
          "team": "blue",
          "x": 54,
          "y": 18
        },
        "blue_3": {
          "has_disc": false,
          "team": "blue",
          "x": 58,
          "y": 31
        },
        "blue_4": {
          "has_disc": false,
          "team": "blue",
          "x": 56,
          "y": 47
        },
        "blue_5": {
          "has_disc": false,
          "team": "blue",
          "x": 52,
          "y": 59
        },
        "red_1": {
          "has_disc": false,
          "team": "red",
          "x": 44,
          "y": 37
        },
        "red_2": {
          "has_disc": false,
          "team": "red",
          "x": 53,
          "y": 20
        },
        "red_3": {
          "has_disc": false,
          "team": "red",
          "x": 57,
          "y": 33
        },
        "red_4": {
          "has_disc": false,
          "team": "red",
          "x": 55,
          "y": 49
        },
        "red_5": {
          "has_disc": false,
          "team": "red",
          "x": 51,
          "y": 61
        }
      },
      "possession_team": "blue",
      "score_team": null,
      "stack": {
        "called_by": null,
        "called_frame": null,
        "state": "none"
      },
      "stall": {
        "active": true,
        "count": 0,
        "limit": 5,
        "marker": "red_1",
        "remaining": 5,
        "thrower": "blue_1"
      },
      "stop_reason": null,
      "stopped": false
    },
    "frame": 0,
    "packet_type": "v2_shared_frame_context",
    "previous_public_frames": []
  }
}
```
