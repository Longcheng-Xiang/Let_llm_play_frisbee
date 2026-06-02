# Game Rules And Configuration

This is the current final configuration used by the included demo.

## Field

| Setting | Value |
|---|---:|
| Field size | `202 x 74` grid cells |
| Cell size | `0.5 m` |
| Left end zone | `x = 0..36` |
| Central field | `x = 37..164` |
| Right end zone | `x = 165..201` |
| Blue attack direction | `+x` |
| Red attack direction | `-x` |
| Frame duration | `1` simulated second |

## Core Rules

- The disc holder cannot move.
- Non-holders may move up to their max movement budget.
- Two players cannot occupy the same coordinate.
- A catch or block is checked within a 2-cell radius.
- A marker starts the stall count if they are within a 2-cell marking radius.
- Stall 5 is a turnover.
- First score ends the point.
- A thrown disc travels in a straight line with constant velocity.
- Out-of-bounds disc flight is a turnover.
- On out-of-bounds turnover, the restart cell is the nearest central-zone cell to where the disc crossed out.

For the reasoning behind these rules and the exact frame-by-frame resolution order, see `system_design.md`.

## V2 Passing Rule

Passing uses a two-frame commitment:

1. The thrower may choose `signal_throw` to make private eye contact with one teammate.
2. On the next frame, if still holding the disc, the thrower must release that committed pass with `throw`.

In V2, only the intended receiver and that receiver's fixed defender can catch/block the active pass. This keeps the first version readable and makes defensive matchups clear.

## Default Live Configuration

| Setting | Default |
|---|---:|
| Version | `V2 Awake` |
| Model | `V4 Flash` |
| Thinking | `On` |
| Frame Upper Limit | `20` |
| Throw Score | `100` |
| Max Disc Speed | `18` cells/frame |
| Recent history frames | `4` |

`Throw Score = 100` removes trajectory uncertainty, so throw paths are deterministic. This makes agent decisions and disc physics easier to inspect.

## Player Stats

The stats are part of the agent-world design. They are deliberately small enough for a model to reason about in a prompt:

- `speed` determines maximum movement per frame.
- `height` affects catch probability and contested-disc tie-breaking.
- `throw` determines angular throw uncertainty.

| Player | Team | Height | Speed | Throw | Max Move |
|---|---|---:|---:|---:|---:|
| `blue_1` | blue | 58 | 63 | 88 | 12 |
| `blue_2` | blue | 82 | 71 | 54 | 12 |
| `blue_3` | blue | 74 | 86 | 48 | 14 |
| `blue_4` | blue | 66 | 78 | 70 | 12 |
| `blue_5` | blue | 91 | 55 | 42 | 10 |
| `red_1` | red | 61 | 68 | 84 | 12 |
| `red_2` | red | 77 | 74 | 52 | 12 |
| `red_3` | red | 69 | 91 | 46 | 14 |
| `red_4` | red | 73 | 72 | 68 | 12 |
| `red_5` | red | 94 | 50 | 40 | 10 |

Live trials can override every throw score to `100`.

## Speed Mapping

| Speed Score | Max Cells/Frame |
|---:|---:|
| `1..20` | 6 |
| `21..40` | 8 |
| `41..60` | 10 |
| `61..80` | 12 |
| `81..100` | 14 |

## Fixed Matchups

| Blue | Red |
|---|---|
| `blue_1` | `red_1` |
| `blue_2` | `red_2` |
| `blue_3` | `red_3` |
| `blue_4` | `red_4` |
| `blue_5` | `red_5` |

The matchup number is shown in the viewer as B1/R1, B2/R2, and so on.
