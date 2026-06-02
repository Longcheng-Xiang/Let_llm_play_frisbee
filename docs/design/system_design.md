# System Design

This project is a small agent world, not a full ultimate frisbee simulator. The design goal is to make the agent loop inspectable: models choose tactics, while deterministic code handles rules, physics, logging, and replay.

## Design Snapshot

- The model controls one player at a time and returns one JSON action.
- The simulator resolves all physical rules, including movement, throws, catches, blocks, turnovers, stall count, and scoring.
- V2 does not use fixed vertical-stack tactics. The current disc holder is the thrower, and every teammate without the disc is a possible receiver.
- Fixed matchups make defense readable: `blue_1` is always guarded by `red_1`, `blue_2` by `red_2`, and so on.
- The viewer and HTML report are part of the design, because the project needs to be inspected frame by frame.

## Frame Logic

Each frame follows the same sequence:

1. The simulator starts from the current world state.
2. The awake/sleep controller decides which players need model calls.
3. Each awake player receives a prompt packet for only that player.
4. The model returns one JSON action.
5. Sleeping players continue stored `move_intent` targets through the controller.
6. The simulator normalizes actions and resolves the frame in this order:
   - public talk or public calls,
   - movement and collisions,
   - pass signal or committed throw release,
   - disc flight, catch, block, drop, out of bounds, or score,
   - stall count if the disc is still held.
7. The frame result is written to the JSONL log and can be replayed in the viewer.

The model calls are stateless provider calls. Memory comes from the observation packet, not from a hidden chat transcript. The recommended viewer setup sends 4 recent history frames, public events, private events for that player, current stored intent, and the current public state.

## Prompt Structure

V2 prompts have two layers:

- A stable system prompt explains the rules, constants, roster, action schema, and tactical basics.
- A per-frame user packet contains structured JSON for the current player.

The user packet is split into:

- `shared_frame_context`: public state, recent public frames, and awake/sleep board.
- `player_decision_context`: this player's private decision request, tactical context, stored intent, private recent frames, legal actions, and output requirements.

This keeps common rules stable while making each frame-specific decision concrete.

## Pass Timing

Passing uses a two-frame commitment so receivers can react without giving all players private knowledge too early.

1. In frame `N`, the thrower may choose `signal_throw` to make private eye contact with one teammate. The disc stays in the thrower's hand.
2. In frame `N + 1`, the thrower and intended receiver are awake. The thrower must release the committed pass if still holding the disc. The receiver knows about the eye contact and can adjust.
3. During the release frame, the simulator creates a constant-velocity disc and immediately advances the first flight segment. If no catch/block/out-of-bounds event resolves it, the next frame starts with the disc still flying.

The pending pass is primarily surfaced to the thrower and receiver. After the disc is released, the active pass context identifies the contest pair so other awake players can reposition around the public flight.

## Player Stats And Abilities

Player stats are intentionally simple:

| Stat | Meaning |
|---|---|
| `speed` | Maps to maximum cells the player can move in one frame. |
| `height` | Controls offensive catch probability and tie-breaking for contested disc contact. |
| `throw` | Controls angular uncertainty on released throws. |

Speed maps to movement budget through `max_move_cells_for_speed` in `frisbee_5v5/config.py`.

Throw uncertainty is:

```text
sigma_degrees = max(0, 18 * (100 - throw_score) / 100)
```

So `throw = 100` gives deterministic throw direction. The recommended demo setting uses `Throw Score = 100` to make disc trajectory debugging clear.

Offensive catch probability is:

```text
clamp(0.50 + height / 200, 0.55, 0.97)
```

This means taller players are better receivers, but no receiver is perfectly guaranteed unless future rules change.

## Catch, Block, And Disc Judgement

The disc moves as a straight segment each frame from its previous coordinate to its next coordinate. Players also move from their previous coordinate to their resolved coordinate.

For each eligible player, the simulator computes the closest approach between the player's movement segment and the disc's movement segment. If that distance is within the 2-cell catch/block radius, that player can contest the disc.

If multiple players can contest:

- the earliest contact on the disc path wins,
- contacts within a small tolerance are treated as simultaneous,
- the tallest player wins a simultaneous contest,
- exact height ties use deterministic random choice from the seeded simulator.

In V2, a flying pass can only be contested by the intended receiver and that receiver's fixed defender. This makes early gameplay easier to understand and keeps each pass focused on one matchup.

If the selected player is on defense, it is a defensive block and turnover. If the selected player is on offense, the catch probability is tested. A catch keeps possession and may score; a failed catch is a turnover.

If the disc leaves the field before anyone contests it, the simulator finds the field exit point, moves the restart to the nearest central-zone cell, and gives the disc to the nearest player on the gaining team.

## Awake/Sleep Design

V2 reduces cost without removing physical players from the game:

- all 10 players are resolved every frame,
- only awake players call the model,
- sleeping players follow stored `move_intent` targets,
- players wake when they have no valid intent, hold the disc, receive eye contact, contest a flying disc, hit reset events, or need to recover from blocked movement.

The thrower sees teammate movement intents, including target, planned next position, and expiry frame. This lets the thrower reason about where a sleeping teammate will likely be.

## What To Modify

- Change field, roster, stats, matchups, and initial positions in `frisbee_5v5/config.py`.
- Change core physics and turnover logic in `frisbee_5v5/simulator.py`.
- Change awake/sleep policy in `frisbee_5v5/awake_controller.py`.
- Change V2 prompts and action parsing in `frisbee_5v5/deepseek_agents_v2.py`.
- Change UI defaults and controls in `viewer/index.html` and `viewer/replay.js`.
