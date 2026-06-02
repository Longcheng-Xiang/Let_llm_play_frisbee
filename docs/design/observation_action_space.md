# Observation And Action Space

The harness turns simulator state into a structured prompt packet. The model must return one compact JSON action. The simulator then validates and resolves that action.

## Observation Shape

Each awake player receives an observation for only that player. Important fields:

| Field | Purpose |
|---|---|
| `current_state` | Full current game state, including players, possession, stall, disc state, pending pass, and score status. |
| `public_current_state` | Public state used in V2 prompts to reduce repeated private detail. |
| `tactical_context` | Role-specific helper facts: team possession, matchup, thrower, marker, passing options, defender positions, active disc context. |
| `legal_action_notes` | Which actions are legal for this player this frame. |
| `awake_context` | V2 awake/sleep details: why this player is awake, who is sleeping, stored movement intents, active disc receiver/defender. |
| `previous_frames_public` | Recent public events. |
| `previous_frames_private_for_you` | Recent private events relevant to this player. |
| `stored_intent_for_you` | Current V2 move intent, if the player is executing one. |
| `constants` | Field dimensions, catch radius, marking radius, max disc speed, and related rule numbers. |
| `roster` | Player stats: team, captain, height, speed, throw score, and max movement. |

The model is told not to invent hidden memory. It should use only the observation packet and stable rules.

## Disc Information

When the disc is flying, observations include:

- current disc coordinate,
- velocity vector,
- speed,
- direction unit vector,
- future path points,
- whether future path points remain in bounds,
- last throw metadata.

This is intentional. The model should not spend effort recomputing basic trajectory if the simulator can provide it exactly.

## Action Space

The model returns exactly one JSON object.

### Move Intent

Used in V2 for sleeping-controller movement.

```json
{"action":"move_intent","target":{"x":120,"y":37},"duration_frames":4,"reason":"cut into open space"}
```

### Direct Move

Used for one-frame urgent movement, especially catching or defending a flying disc.

```json
{"action":"move","target":{"x":140,"y":42},"reason":"contest disc path"}
```

### Signal Throw

Private eye contact with one teammate. This commits the thrower to release the pass on the next frame if still holding the disc.

```json
{"action":"signal_throw","intended_receiver":"blue_3","reason":"safe lane"}
```

### Throw

Releases a committed pass.

```json
{"action":"throw","target":{"x":160,"y":35},"intended_receiver":"blue_3","throw_side":"forehand","disc_speed":18,"reason":"lead receiver"}
```

### Hold

```json
{"action":"hold","reason":"no safe option"}
```

### Talk

Public speech heard by both teams.

```json
{"action":"talk","message":"reset left","reason":"organize spacing"}
```

## Why Structured JSON

The simulator needs executable actions, not just plausible sports commentary. JSON makes each model decision inspectable, testable, and safe to normalize before applying physics.

Invalid or malformed actions are converted to safe fallbacks by the parser and simulator.
