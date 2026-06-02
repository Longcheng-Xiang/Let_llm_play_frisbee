# Frisbee 5v5 Agent World

This project places LLM-controlled agents into a 5v5 frisbee world. Each player observes their environment in a structured format, and returns an action in a structured format. During each frame, we can see clearly what each agent is thinking, as well as the interactions between them (for example, an "eye contact" between the thrower and the receiver of the frisbee).

The simulator resolves movement, throws, catches, blocks, turnovers, stall count, and scoring of the game.

The current submitted version is optimized and tested around DeepSeek, specifically `deepseek-v4-flash` with thinking enabled. Other providers can be used, but the model adapter, reasoning option, usage parsing, cache accounting, and cost estimator are DeepSeek-specific today.

## Start Here: Open The Viewer

You can get familiar with the project quickly by directly inspecting the included 19-frame scoring demo without an API token. The replay log is `examples/runs/final_demo_19f_score.jsonl`, and the viewer loads it by default.

```bash
# after cloning or downloading this repository
cd Let_llm_play_frisbee
python3 scripts/serve_live_trial.py --port 8766
```

Open:

```text
http://127.0.0.1:8766/viewer/
```

Use `Next`, `Prev`, `Play`, the timeline, and the player selector to inspect what happened. The `Agent Log` shows each awake agent's action, reason, API latency, usage, raw response, and returned thinking trace when available.

To run a live game controlled by agents, create a local `.env` file first:

```bash
cp .env.example .env
```

Then edit `.env` and add your key:

```text
DEEPSEEK_API_KEY=your_token_here
```

Restart the server if it was already running, then use the recommended locked default UI settings:

- Version: `V2 Awake`
- Model: `V4 Flash`
- Thinking: `On`
- Frame Upper Limit: `20`
- Throw Score: `100`
- Max Disc Speed: `18`

Press `Start Trial` to play a new point. Press `Stop Trial` to stop the local run; already-started provider requests may still finish server-side.

## Example Outputs

The submission includes two model-run examples and a silent UI walkthrough.

[![Silent UI demo video thumbnail](docs/media/frisbee-demo-thumbnail.png)](https://longcheng-xiang.github.io/Let_llm_play_frisbee/#example-runs)

Click the image above to watch the silent UI demo video on GitHub Pages. The video file is also available at [docs/media/frisbee-project-demo-video.mp4](docs/media/frisbee-project-demo-video.mp4).

**Blue score demo**

- Log: [examples/runs/final_demo_19f_score.jsonl](examples/runs/final_demo_19f_score.jsonl)
- Report: [examples/runs/final_demo_19f_score_report.html](examples/runs/final_demo_19f_score_report.html)
- Setup: latest V2 awake/sleep, `deepseek-v4-flash`, thinking on, throw score `100`, max disc speed `18`
- Result: 19 frames, 135 API calls, estimated `$0.112026`, stop reason `score`

**Red score live run**

- Log: [examples/runs/red_score_8f_live.jsonl](examples/runs/red_score_8f_live.jsonl)
- Report: [examples/runs/red_score_8f_live_report.html](examples/runs/red_score_8f_live_report.html)
- Result: 8 frames, 48 API calls, estimated `$0.039028`, stop reason `score`

## Simple Frisbee Rules

![Field and scoring direction](docs/assets/simple_rules_field.svg)

- Blue scores by catching the disc in the right end zone.
- Red scores by catching the disc in the left end zone.
- The player holding the disc cannot run.
- Teammates without the disc move to open space.
- A completed catch keeps possession.
- A block, interception, dropped catch, out-of-bounds throw, or stall turnover gives possession to the other team.
- In this simulation, the first score ends the point.

What this project achieves relative to those rules:

- Agents see all player positions, player stats, possession, stall count, legal actions, disc state, disc velocity, and future disc path.
- The simulator, not the model, enforces movement limits, collisions, catch/block radius, turnovers, and scores.
- The model only chooses structured actions: `move`, `move_intent`, `hold`, `talk`, `signal_throw`, or `throw`.
- V2 uses an awake/sleep controller so only tactically relevant players call the model each frame.

For the short visual rule guide, see `docs/simple_frisbee_rules.md`.

## Cost And Models

Live trials make paid API calls. This project was tested with DeepSeek models, especially `deepseek-v4-flash` with thinking enabled. Costs vary by provider and pricing changes, so treat the built-in cost values as estimates.

The V2 awake/sleep version reduces cost by calling the model only for needed players. Sleeping players continue stored `move_intent` targets through a deterministic controller. The included 19-frame scoring demo used 135 calls and cost about `$0.112026` by the current DeepSeek price table in the code.

The current prompt and cost structure are DeepSeek-oriented. The adapter sends DeepSeek-style `thinking` and JSON response options, reads returned `reasoning_content`, and estimates cost from DeepSeek usage fields such as `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`. The prompt is split into stable rules plus compact per-frame JSON so repeated input is friendly to DeepSeek's provider-side prompt cache. For another provider, update the adapter and cost/caching logic before trusting the UI cost estimate.

The UI default uses a 20-frame upper limit, but a point can end earlier through a score, turnover flow, stop request, cost limit, or API-call limit.

## Changing The Model

The current adapter is DeepSeek-shaped. If you have a different provider, such as OpenAI, update:

- `frisbee_5v5/deepseek_agents.py`
- `frisbee_5v5/deepseek_agents_v2.py`
- `frisbee_5v5/live_server.py`
- `frisbee_5v5/deepseek_probe.py`
- `viewer/index.html` if you want different UI labels

The important pieces are the request payload, authentication, response parser, JSON action extraction, thinking/reasoning parameter, timeout behavior, usage parsing, prompt-cache accounting, and cost estimator. More detail is in `docs/design/model_switching.md`.

## Tests

Run the local test suite:

```bash
python3 -m unittest discover -s tests
```

No model calls are made by the tests.

## Design Docs

Start with `docs/design/README.md` if you want to understand the design before reading code.

- `docs/design/system_design.md`: architecture, frame logic, prompt structure, player stats, catch/block judgement, and awake/sleep design.
- `docs/design/development_stages.md`: short history of the design sequence.
- `docs/design/project_structure.md`: what every submitted file does.
- `docs/design/observation_action_space.md`: what agents see and what actions they can return.
- `docs/design/example_prompt.md`: one complete public-safe V2 prompt packet for an awake player decision.
- `docs/design/game_rules_and_config.md`: field, player stats, stall count, throw score, disc speed, and default settings.
- `docs/design/cost_and_models.md`: API usage, costs, stop behavior, and tested model setup.
- `docs/design/model_switching.md`: how to adapt the project to another provider.

## Public GitHub Pages Site

This section is for anyone publishing or reviewing the public static website. GitHub Pages is static, so it cannot run the Python server or call a model API. It presents the project, rules, design notes, demo video, and example reports. The Pages entry file is:

```text
docs/index.html
```

After pushing to GitHub, enable Pages from the `main` branch and `/docs` folder.
