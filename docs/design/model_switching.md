# Changing Models

The current implementation is tested with DeepSeek and optimized around DeepSeek V4 Flash with thinking enabled. Another provider can be used, but it is not a drop-in setting change because each provider has its own request format, response shape, reasoning options, cache accounting, and pricing.

## Current DeepSeek Assumptions

The current adapter assumes:

- a DeepSeek chat-completions endpoint,
- a DeepSeek-style `thinking` request option,
- JSON mode through `response_format`,
- returned thinking text in `reasoning_content`,
- usage fields such as `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens`,
- local price estimates from `frisbee_5v5/deepseek_probe.py`.

The prompt is intentionally split into stable rules plus compact per-frame JSON so repeated input can benefit from DeepSeek provider-side prompt caching. If another provider reports cache usage differently, the UI and report cost estimate should be adjusted.

## Fast Path: Another DeepSeek Model

If the model uses the same DeepSeek chat completions API:

1. Unlock the viewer settings.
2. Change the `Model` selector if the option already exists.
3. If needed, update model labels/options in `viewer/index.html`.
4. Update the server default in `frisbee_5v5/live_server.py`.
5. Update the price table in `frisbee_5v5/deepseek_probe.py`.
6. Run a small trial first.

## OpenAI Or Another Provider

For OpenAI or another non-DeepSeek provider, update or replace the adapter files:

```text
frisbee_5v5/deepseek_agents.py
frisbee_5v5/deepseek_agents_v2.py
```

The adapter must handle:

- authentication header,
- endpoint URL,
- model name,
- request payload shape,
- JSON response extraction,
- reasoning/thinking option, if supported,
- timeout and stop behavior,
- usage parsing,
- prompt-cache accounting,
- cost estimation.

The rest of the simulator can stay mostly unchanged if the adapter still returns a `ModelActionResult` containing one parsed action object.

## Places To Check

| File | Why |
|---|---|
| `frisbee_5v5/deepseek_agents.py` | V1 payload, parser, model call. |
| `frisbee_5v5/deepseek_agents_v2.py` | V2 payload, parser, model call. |
| `frisbee_5v5/live_server.py` | UI/API defaults, max token defaults, selected model/thinking. |
| `frisbee_5v5/deepseek_probe.py` | API-key loading, concurrency probe, cost table. |
| `viewer/index.html` | Visible model choices. |
| `viewer/replay.js` | Start-trial request body and UI defaults. |

## Keep The Action Contract

Whatever model you use, make it return one compact JSON action:

```json
{"action":"hold","reason":"no safe option"}
```

The simulator depends on this contract. If a model produces free-form text, add a parser or repair layer before sending actions into the simulator.
