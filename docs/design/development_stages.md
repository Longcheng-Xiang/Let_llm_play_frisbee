# Development Stages

This is a short history of how the project design took shape. It is not a changelog of every code edit; it explains the main design sequence.

## 1. Frisbee Rules

The first design step was to define the simplified frisbee world:

- two 5-player teams,
- a rectangular grid field with two end zones,
- one disc holder who cannot run,
- movement by non-holders,
- catches, blocks, drops, out-of-bounds turnovers, stall turnovers, and scoring.


## 2. Player Abilities

The next step was to define small, readable player abilities:

- `speed`: how far a player can move in one frame,
- `height`: how likely a player is to catch and who wins close contested-disc situations (in real situations the ability to catch is not that much correlated with height; in here I just made a simplification),
- `throw`: how much angular uncertainty a throw has.

These abilities are simple enough to fit in every agent prompt, but still matter tactically.

## 3. World Configuration

After the rules and abilities, the project needed fixed simulation settings:

- grid size and end-zone coordinates,
- one-second frame timing,
- catch/block radius,
- marking radius and stall limit,
- maximum disc speed,
- initial player positions,
- fixed B1/R1, B2/R2, etc. matchups.

The current recommended setup uses `Throw Score = 100`, so the throw trajectory is deterministic and easier to inspect.

## 4. Strategy And Agent Timing

The strategy design changed during development. An early idea used vertical-stack tactics, but that was not a good fit for the first public version because it added role complexity before the basic agent world was stable.

V2 instead uses a simpler open-movement game:

- whoever holds the disc is the thrower,
- every teammate without the disc is a possible receiver,
- defenders stay responsible for fixed numbered matchups,
- the thrower can hold, talk, or signal a pass,
- a signaled pass is released on the next frame,
- the receiver and defender react to the disc path after the release.

This led to the two-frame pass design: eye contact first, then release. It also led to giving agents computed helper facts, such as defender distance to a passing lane, disc velocity, and future disc path, so the model can spend more attention on tactics instead of basic geometry.

## 5. Awake/Sleep Cost Control

The final major design stage was cost control. Calling every player every frame was expensive and often unnecessary.

V2 keeps all 10 players physically active, but only wakes players who need a model decision. Sleeping players continue stored `move_intent` targets through a deterministic controller. The thrower can see teammate intents and expiry frames, so they can reason about where sleeping teammates are likely to move.

This keeps the game inspectable while making live model trials cheaper.
