# Project Structure

This map explains what each submitted file does.

## Top Level

| Path | Purpose |
|---|---|
| `.env.example` | Example local API-key file. Copy to `.env` and edit locally; do not commit `.env`. |
| `.gitignore` | Prevents local tokens, caches, generated logs, and operating-system files from entering the repository. |
| `README.md` | Main project introduction, run instructions, demo summary, rules, cost notes, and links to design docs. |
| `pyproject.toml` | Python project metadata and package configuration. |

## Python Package

| Path | Purpose |
|---|---|
| `frisbee_5v5/__init__.py` | Package marker. |
| `frisbee_5v5/awake_controller.py` | V2 awake/sleep controller, stored movement intents, wake reasons, and controller movement for sleeping players. |
| `frisbee_5v5/cli.py` | Command-line entry point used by scripts. |
| `frisbee_5v5/config.py` | Field size, roster, player stats, speed mapping, fixed matchups, initial positions, and rule constants. |
| `frisbee_5v5/deepseek_agents.py` | V1 model adapter, action parsing, usage normalization, and cost estimation helpers. |
| `frisbee_5v5/deepseek_agents_v2.py` | V2 prompt, V2 payload builder, V2 model call, JSON action parser, and V2 action repair. |
| `frisbee_5v5/deepseek_probe.py` | API-key loading, DeepSeek connectivity probe, dry run, concurrency test, and local price table. |
| `frisbee_5v5/live_runner.py` | V1 live game runner and shared run-limit/status helpers. |
| `frisbee_5v5/live_runner_v2.py` | V2 live game runner: awake model calls, simulator stepping, logging, cost accumulation, and report generation. |
| `frisbee_5v5/live_server.py` | Local HTTP server for the viewer, live trial API, logs, reports, and trial controls. |
| `frisbee_5v5/policies.py` | Non-model policies used for local/offline simulation tests. |
| `frisbee_5v5/report.py` | Converts JSONL trial logs into readable HTML reports. |
| `frisbee_5v5/simulator.py` | Core simulator: observations, movement, pass timing, disc physics, catch/block judgement, turnovers, stall, and scoring. |

## Scripts

| Path | Purpose |
|---|---|
| `scripts/serve_live_trial.py` | Starts the local live-trial server and viewer. |
| `scripts/run_offline_simulation.py` | Runs a local non-model simulation for quick simulator checks. |
| `scripts/test_deepseek_concurrency.py` | Probes DeepSeek model/API behavior, with a dry-run mode that avoids paid calls. |

## Viewer

| Path | Purpose |
|---|---|
| `viewer/index.html` | Main replay/live-trial UI. |
| `viewer/replay.js` | Viewer logic: loading logs, drawing the field, controlling playback, starting/stopping trials, and applying UI defaults. |
| `viewer/styles.css` | Viewer and UI-guide styling. |
| `viewer/ui-guide.html` | Separate UI guide page opened from the viewer. |

## Public Docs For GitHub Pages

| Path | Purpose |
|---|---|
| `docs/.nojekyll` | Tells GitHub Pages to serve files directly without Jekyll processing. |
| `docs/index.html` | Static GitHub Pages landing page served by the public site. |
| `docs/index.md` | Markdown copy of the Pages content for readers who prefer repository text. |
| `docs/simple_frisbee_rules.md` | Short visual rule guide for readers new to frisbee. |
| `docs/examples/final_demo_19f_score_report.html` | Static copy of the included final demo report for GitHub Pages. |
| `docs/examples/red_score_8f_live_report.html` | Static copy of the included 8-frame red-score report for GitHub Pages. |
| `docs/media/frisbee-project-demo-video.mp4` | Public-safe cropped silent UI walkthrough video. |
| `docs/assets/simple_rules_field.svg` | Field and scoring direction illustration. |
| `docs/assets/simple_rules_flow.svg` | Simple play-flow illustration. |
| `docs/assets/simple_rules_stall_turnover.svg` | Stall and turnover illustration. |

## Design Docs

| Path | Purpose |
|---|---|
| `docs/design/README.md` | Reading order for the design documentation. |
| `docs/design/development_stages.md` | Short history of the project design sequence. |
| `docs/design/system_design.md` | Architecture, frame logic, prompt structure, player stats, catch/block judgement, and awake/sleep design. |
| `docs/design/project_structure.md` | This file. |
| `docs/design/observation_action_space.md` | Detailed observation fields and legal JSON actions. |
| `docs/design/game_rules_and_config.md` | Field constants, default settings, player stats, fixed matchups, and rule configuration. |
| `docs/design/cost_and_models.md` | Tested model setup, API cost, V2 cost saving, stop behavior, and token safety. |
| `docs/design/model_switching.md` | How to switch to another DeepSeek model or adapt the adapter for another provider. |

## Example Run

| Path | Purpose |
|---|---|
| `examples/runs/final_demo_19f_score.jsonl` | Included 19-frame scoring demo log. |
| `examples/runs/final_demo_19f_score_report.html` | HTML report generated from the demo log. |
| `examples/runs/red_score_8f_live.jsonl` | Included 8-frame red-score live-run log. |
| `examples/runs/red_score_8f_live_report.html` | HTML report generated from the 8-frame red-score log. |

## Tests

| Path | Purpose |
|---|---|
| `tests/test_deepseek_agents.py` | V1 model adapter and parser tests. |
| `tests/test_deepseek_probe.py` | API-key loading, placeholder-token handling, and probe helper tests. |
| `tests/test_live_runner_stop.py` | Stop behavior tests for live runners. |
| `tests/test_live_server.py` | Local server API tests. |
| `tests/test_report.py` | HTML report generation tests. |
| `tests/test_simulator.py` | Simulator rules, movement, throw, catch, turnover, and scoring tests. |
| `tests/test_v2_awake_sleep.py` | V2 awake/sleep, stored-intent, and V2 runner tests. |
