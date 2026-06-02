# Cost And Model Setup

The live system can make paid API calls. The included demo was tested with DeepSeek models, especially V4 Flash with thinking enabled.

## Tested Default

| Setting | Value |
|---|---|
| Provider | DeepSeek |
| Model | `deepseek-v4-flash` |
| Thinking | enabled |
| Version | V2 awake/sleep |
| Frame upper limit | 20 |
| Throw score | 100 |
| Max disc speed | 18 |

## Included Demo Cost

The official demo log is:

```text
examples/runs/final_demo_19f_score.jsonl
```

It ended with a blue score:

| Metric | Value |
|---|---:|
| Frames | 19 |
| API calls | 135 |
| Estimated cost | `$0.112026` |
| Stop reason | `score` |

Cost is estimated from the local price table in `frisbee_5v5/deepseek_probe.py`. Provider pricing can change, so treat the number as a run-specific estimate rather than a guarantee.

## Why V2 Is Cheaper

V1 calls all 10 players every frame.

V2 calls only awake players. Sleeping players follow stored `move_intent` targets through the deterministic controller. The simulator still resolves all 10 physical actions every frame.

Players tend to wake when they are:

- the current thrower,
- the committed receiver,
- the intended receiver of a flying disc,
- the fixed defender of that intended receiver,
- at point start or after certain reset events,
- out of usable stored intent.

## Stop Behavior

`Stop Trial` stops the local run and abandons waiting for active model calls. Already-started provider requests may still finish server-side and may still be billed, but the UI should not remain stuck waiting for them.

## Token Safety

The repository should include `.env.example`, not `.env`.

Use either:

```bash
export DEEPSEEK_API_KEY=your_token_here
```

or:

```bash
cp .env.example .env
```

Then edit `.env` locally. Do not commit it.
