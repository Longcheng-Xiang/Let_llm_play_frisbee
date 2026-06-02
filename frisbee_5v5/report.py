from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def read_jsonl_events(path: str | Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def write_accessible_report(log_path: str | Path, report_path: str | Path | None = None) -> Path:
    source = Path(log_path)
    target = Path(report_path) if report_path else source.with_name(f"{source.stem}_report.html")
    target.write_text(build_accessible_report(read_jsonl_events(source), source.name), encoding="utf-8")
    return target


def build_accessible_report(events: list[dict[str, Any]], title: str = "frisbee run") -> str:
    start = next((event for event in events if event.get("type") == "episode_start"), None)
    frames = [event for event in events if event.get("type") == "frame"]
    end = next((event for event in reversed(events) if event.get("type") == "episode_end"), None)
    players = sorted((start or {}).get("state", {}).get("players", {}).keys())

    body: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        f"<title>{esc(title)} Agent Report</title>",
        "<style>",
        REPORT_CSS,
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        "<header>",
        "<p>Frisbee 5v5</p>",
        f"<h1>{esc(title)} Agent Report</h1>",
        summary_grid(start, frames, end),
        player_filter(players),
        "</header>",
    ]
    for index, frame in enumerate(frames, start=1):
        body.append(frame_section(index, frame))
    if not frames:
        body.append("<section><h2>No frame events</h2><p>This log does not contain replay frames yet.</p></section>")
    body.extend(
        [
            "</main>",
            "<script>",
            REPORT_JS,
            "</script>",
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(body)


def summary_grid(start: dict[str, Any] | None, frames: list[dict[str, Any]], end: dict[str, Any] | None) -> str:
    start_state = (start or {}).get("state", {})
    cells = {
        "Version": (start or {}).get("game_version", "v1_roleless"),
        "Model": (start or {}).get("model", "-"),
        "Thinking": (start or {}).get("thinking", "-"),
        "Seed": (start or {}).get("seed", "-"),
        "Frames": (end or {}).get("frames", len(frames)),
        "API Calls": (end or {}).get("api_calls", "-"),
        "Cost": money((end or {}).get("estimated_cost_usd")),
        "Stop": (end or {}).get("stop_reason", "-"),
        "Initial Possession": start_state.get("possession_team", "-"),
    }
    items = []
    for label_text, value in cells.items():
        items.append(f"<div><span>{esc(label_text)}</span><strong>{esc(value)}</strong></div>")
    return f'<section class="summary-grid">{"".join(items)}</section>'


def player_filter(players: list[str]) -> str:
    options = ['<option value="all">all players</option>']
    options.extend(f'<option value="{esc(player)}">{esc(player)}</option>' for player in players)
    return (
        '<label class="filter-row">'
        "<span>Filter agent</span>"
        f'<select id="player-filter">{"".join(options)}</select>'
        "</label>"
    )


def frame_section(index: int, frame: dict[str, Any]) -> str:
    frame_start = frame.get("frame_start", index - 1)
    frame_end = frame.get("frame_end", index)
    status = frame_status(frame)
    cards = "".join(model_result_card(result) for result in sorted(frame.get("model_results", []), key=player_sort_key))
    if not cards:
        cards = '<p class="empty">No model calls recorded for this frame.</p>'
    events = "".join(f"<li>{esc(event_label(event))}</li>" for event in frame.get("events", []))
    if not events:
        events = "<li>No simulator events.</li>"
    raw_json = esc(json.dumps(frame, indent=2, sort_keys=True))
    return (
        f'<section class="frame-block" data-frame="{esc(frame_end)}">'
        f"<h2>Frame {esc(frame_start)} -> {esc(frame_end)}</h2>"
        f'<div class="frame-meta">{status}</div>'
        f'<div class="agent-grid">{cards}</div>'
        "<details>"
        "<summary>Simulator events</summary>"
        f"<ol>{events}</ol>"
        "</details>"
        "<details>"
        "<summary>Full frame JSON</summary>"
        f"<pre>{raw_json}</pre>"
        "</details>"
        "</section>"
    )


def frame_status(frame: dict[str, Any]) -> str:
    awake_sleep = frame.get("awake_sleep", {}) if isinstance(frame.get("awake_sleep"), dict) else {}
    awake = awake_sleep.get("awake_players", [])
    sleeping = awake_sleep.get("sleeping_players", [])
    cells = {
        "Wall time": f"{frame.get('wall_seconds', '-')}s",
        "Frame cost": money(frame.get("estimated_cost_usd")),
        "Cumulative cost": money(frame.get("cumulative_estimated_cost_usd")),
        "Usage": token_summary(frame.get("usage", {})),
        "Awake/Sleep": f"{len(awake)} awake, {len(sleeping)} sleeping" if awake_sleep else "-",
    }
    return "".join(f"<div><span>{esc(label_text)}</span><strong>{esc(value)}</strong></div>" for label_text, value in cells.items())


def model_result_card(result: dict[str, Any]) -> str:
    player_id = str(result.get("player_id", "-"))
    action = result.get("action", {}) if isinstance(result.get("action"), dict) else {}
    status_class = "ok" if result.get("ok") else "error"
    usage = result.get("usage", {}) if isinstance(result.get("usage"), dict) else {}
    details: list[str] = []
    if action.get("reason"):
        details.append(f'<p class="reason">{esc(action.get("reason"))}</p>')
    if result.get("reasoning_content"):
        details.append(
            "<details><summary>Returned thinking trace</summary>"
            f"<pre>{esc(result.get('reasoning_content'))}</pre></details>"
        )
    if result.get("raw_content"):
        details.append("<details><summary>Raw model content</summary>" f"<pre>{esc(result.get('raw_content'))}</pre></details>")
    if result.get("error"):
        details.append(f'<p class="error-text">{esc(result.get("error"))}</p>')
    return (
        f'<article class="agent-card {status_class}" data-player="{esc(player_id)}">'
        f"<h3>{esc(player_id)}</h3>"
        f'<div class="pill-row"><span>{esc("ok" if result.get("ok") else "error")}</span>'
        f"<span>{esc(result.get('latency_seconds', '-'))}s</span>"
        f"<span>{esc(action.get('action', '-'))}</span></div>"
        f'<dl><div><dt>Action</dt><dd>{esc(action_label(action))}</dd></div>'
        f'<div><dt>Finish</dt><dd>{esc(result.get("finish_reason", "-"))}</dd></div>'
        f'<div><dt>Usage</dt><dd>{esc(token_summary(usage))}</dd></div></dl>'
        f"{''.join(details)}"
        "</article>"
    )


def player_sort_key(result: dict[str, Any]) -> tuple[str, int]:
    player_id = str(result.get("player_id", ""))
    team, _, suffix = player_id.partition("_")
    try:
        number = int(suffix)
    except ValueError:
        number = 99
    return team, number


def action_label(action: dict[str, Any]) -> str:
    name = action.get("action")
    target = action.get("target")
    if name == "move" and isinstance(target, dict):
        return f"move to ({target.get('x')}, {target.get('y')})"
    if name == "move_intent" and isinstance(target, dict):
        return f"intent to ({target.get('x')}, {target.get('y')}) for {action.get('duration_frames', '-')}f"
    if name == "signal_throw":
        return f"eye contact with {action.get('intended_receiver', '-')}"
    if name == "throw" and isinstance(target, dict):
        return f"throw {action.get('throw_side', '-')} to ({target.get('x')}, {target.get('y')})"
    if name in {"talk", "call_stack"}:
        return f"{name}: {action.get('message', '')}"
    return str(name or "-")


def event_label(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", "event"))
    if event_type == "movement":
        to = event.get("to", {})
        return f"{event.get('player')} moved to ({to.get('x')}, {to.get('y')})"
    if event_type == "pass_intent":
        return f"{event.get('thrower')} made eye contact with {event.get('intended_receiver')}"
    if event_type == "committed_throw_forced":
        return f"{event.get('thrower')} forced committed throw to {event.get('intended_receiver')}"
    if event_type == "throw_released":
        target = event.get("target", {})
        return f"{event.get('thrower')} threw {event.get('throw_side')} toward ({target.get('x')}, {target.get('y')})"
    if event_type == "disc_flying":
        return "disc flying"
    if event_type == "turnover":
        return f"turnover: {event.get('reason')} -> {event.get('new_thrower')}"
    if event_type == "catch":
        return f"{event.get('player')} caught the disc"
    if event_type == "disc_out_of_bounds":
        restart = event.get("restart_spot", {})
        crossing = event.get("crossing", {})
        if isinstance(restart, dict) and isinstance(crossing, dict):
            return (
                f"disc crossed out at ({crossing.get('x')}, {crossing.get('y')}); "
                f"{event.get('restart_player')} restarts at ({restart.get('x')}, {restart.get('y')})"
            )
        return "disc out of bounds"
    return event_type.replace("_", " ")


def token_summary(usage: dict[str, Any]) -> str:
    total = usage.get("total_tokens", "-")
    prompt = usage.get("prompt_tokens", "-")
    completion = usage.get("completion_tokens", "-")
    cache_hit = usage.get("prompt_cache_hit_tokens", 0)
    return f"{total} total, {prompt} in, {completion} out, {cache_hit} cached"


def money(value: Any) -> str:
    try:
        return f"${float(value):.6f}"
    except (TypeError, ValueError):
        return "-"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


REPORT_CSS = """
:root {
  color-scheme: light;
  --bg: #f5f7f4;
  --panel: #ffffff;
  --ink: #172126;
  --muted: #64706f;
  --line: #cbd6d0;
  --blue: #1f6ed4;
  --red: #d43f3a;
  --ok: #e3f5e9;
  --bad: #fff0ed;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); }
main { width: min(1500px, calc(100vw - 28px)); margin: 0 auto; padding: 22px 0 34px; }
header { display: grid; gap: 14px; }
p, h1, h2, h3 { margin: 0; }
header p { color: var(--blue); font-size: 12px; font-weight: 800; text-transform: uppercase; }
h1 { font-size: clamp(27px, 3vw, 42px); line-height: 1.05; }
h2 { font-size: 20px; }
h3 { font-size: 16px; }
.summary-grid, .frame-meta { display: grid; gap: 8px; }
.summary-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.frame-meta { grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 10px 0; }
.summary-grid div, .frame-meta div, .agent-card { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
.summary-grid div, .frame-meta div { padding: 10px 12px; }
span, dt { color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; }
strong, dd { overflow-wrap: anywhere; }
.filter-row { display: flex; align-items: center; gap: 10px; }
select { min-height: 38px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); color: var(--ink); padding: 0 12px; font: inherit; }
.frame-block { margin-top: 18px; }
.agent-grid { display: grid; grid-template-columns: repeat(5, minmax(180px, 1fr)); gap: 10px; }
.agent-card { padding: 12px; min-height: 210px; }
.agent-card.ok { background: var(--ok); }
.agent-card.error { background: var(--bad); border-color: #e3aca3; }
.pill-row { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
.pill-row span { border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,0.7); padding: 4px 8px; text-transform: none; }
dl { display: grid; gap: 7px; margin: 0; }
dd { margin: 2px 0 0; font-size: 13px; }
.reason, .error-text { margin-top: 10px; line-height: 1.45; overflow-wrap: anywhere; }
.error-text { color: #8e1f19; font-weight: 700; }
details { margin-top: 12px; }
summary { cursor: pointer; font-weight: 750; }
pre { max-height: 360px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; background: #101418; color: #edf4ee; padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.hidden { display: none; }
@media (max-width: 1100px) {
  .summary-grid, .frame-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-grid { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
}
@media (max-width: 680px) {
  main { width: min(100vw - 18px, 1500px); }
  .summary-grid, .frame-meta, .agent-grid { grid-template-columns: 1fr; }
}
""".strip()


REPORT_JS = """
const filter = document.querySelector("#player-filter");
filter?.addEventListener("change", () => {
  const selected = filter.value;
  for (const card of document.querySelectorAll("[data-player]")) {
    card.classList.toggle("hidden", selected !== "all" && card.dataset.player !== selected);
  }
});
""".strip()
