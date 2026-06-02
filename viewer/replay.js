const SAMPLE_PATH = "../examples/runs/final_demo_19f_score.jsonl";
const FIELD = {
  width: 202,
  height: 74,
  leftEndZoneMax: 36,
  rightEndZoneMin: 165
};
const FIXED_MATCHUPS = {
  blue_1: "red_1",
  blue_2: "red_2",
  blue_3: "red_3",
  blue_4: "red_4",
  blue_5: "red_5"
};

let replay = {
  frames: [],
  start: null,
  end: null,
  source: "No replay loaded"
};
let frameIndex = 0;
let selectedPlayer = "blue_1";
let timer = null;
let liveStatus = null;
let livePollTimer = null;
let configurationLocked = true;

const elements = {
  configLockToggle: document.querySelector("#config-lock-toggle"),
  startLive: document.querySelector("#start-live"),
  stopLive: document.querySelector("#stop-live"),
  gameVersionSelect: document.querySelector("#game-version-select"),
  modelSelect: document.querySelector("#model-select"),
  thinkingSelect: document.querySelector("#thinking-select"),
  maxFramesInput: document.querySelector("#max-frames-input"),
  throwScoreSelect: document.querySelector("#throw-score-select"),
  discSpeedInput: document.querySelector("#disc-speed-input"),
  loadSample: document.querySelector("#load-sample"),
  reportLink: document.querySelector("#report-link"),
  fileInput: document.querySelector("#file-input"),
  frameLabel: document.querySelector("#frame-label"),
  possessionLabel: document.querySelector("#possession-label"),
  discLabel: document.querySelector("#disc-label"),
  passLabel: document.querySelector("#pass-label"),
  stallLabel: document.querySelector("#stall-label"),
  statusLabel: document.querySelector("#status-label"),
  liveLabel: document.querySelector("#live-label"),
  timeline: document.querySelector("#timeline"),
  prevFrame: document.querySelector("#prev-frame"),
  playToggle: document.querySelector("#play-toggle"),
  nextFrame: document.querySelector("#next-frame"),
  speedSelect: document.querySelector("#speed-select"),
  fieldSvg: document.querySelector("#field-svg"),
  playerSelect: document.querySelector("#player-select"),
  playerPosition: document.querySelector("#player-position"),
  playerRole: document.querySelector("#player-role"),
  playerMatchup: document.querySelector("#player-matchup"),
  playerAttributes: document.querySelector("#player-attributes"),
  playerAction: document.querySelector("#player-action"),
  playerReason: document.querySelector("#player-reason"),
  eventList: document.querySelector("#event-list"),
  playerTable: document.querySelector("#player-table"),
  traceSummary: document.querySelector("#trace-summary"),
  agentLogSummary: document.querySelector("#agent-log-summary"),
  liveAgentStatus: document.querySelector("#live-agent-status"),
  agentLog: document.querySelector("#agent-log")
};

const lockableConfigurationControls = [
  elements.gameVersionSelect,
  elements.modelSelect,
  elements.thinkingSelect,
  elements.throwScoreSelect,
  elements.discSpeedInput
];

function updateConfigurationLock() {
  lockableConfigurationControls.forEach((control) => {
    control.disabled = configurationLocked;
  });
  elements.configLockToggle.textContent = configurationLocked ? "Locked" : "Unlocked";
  elements.configLockToggle.classList.toggle("locked", configurationLocked);
  elements.configLockToggle.classList.toggle("unlocked", !configurationLocked);
  elements.configLockToggle.setAttribute("aria-pressed", String(configurationLocked));
  elements.configLockToggle.title = configurationLocked
    ? "Unlock to change version, model, thinking, throw score, or max disc speed."
    : "Lock version, model, thinking, throw score, and max disc speed.";
}

function parseJsonl(text, source = "Replay", options = {}) {
  const previousIndex = frameIndex;
  const wasAtEnd = frameIndex >= replay.frames.length - 1;
  const events = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));

  const start = events.find((event) => event.type === "episode_start") ?? null;
  const frameEvents = events.filter((event) => event.type === "frame");
  const end = [...events].reverse().find((event) => event.type === "episode_end") ?? null;
  const frames = [];

  if (start?.state) {
    frames.push({
      type: "initial",
      frame_start: 0,
      frame_end: start.state.frame ?? 0,
      actions: {},
      events: [],
      state: start.state
    });
  }
  frames.push(...frameEvents);

  replay = { frames, start, end, source };
  if (options.followLatest || (options.preserveIndex && wasAtEnd)) {
    frameIndex = Math.max(frames.length - 1, 0);
  } else if (options.preserveIndex) {
    frameIndex = Math.min(previousIndex, Math.max(frames.length - 1, 0));
  } else {
    frameIndex = 0;
  }
  if (!frames.some((frame) => frame.state?.players?.[selectedPlayer])) {
    selectedPlayer = firstPlayerId(frames[0]?.state) ?? "blue_3";
    elements.playerSelect.value = selectedPlayer;
  }
  stopPlayback();
  render();
}

async function loadSampleReplay() {
  const response = await fetch(SAMPLE_PATH);
  if (!response.ok) {
    throw new Error(`Could not load sample replay (${response.status})`);
  }
  parseJsonl(await response.text(), "final_demo_19f_score.jsonl");
}

function currentFrame() {
  return replay.frames[frameIndex] ?? null;
}

function currentState() {
  return currentFrame()?.state ?? null;
}

function render() {
  const frame = currentFrame();
  const state = frame?.state;
  elements.timeline.max = String(Math.max(replay.frames.length - 1, 0));
  elements.timeline.value = String(frameIndex);

  if (!state) {
    elements.frameLabel.textContent = "-";
    elements.possessionLabel.textContent = "-";
    elements.discLabel.textContent = "-";
    elements.passLabel.textContent = "-";
    elements.stallLabel.textContent = "-";
    elements.statusLabel.textContent = replay.source;
    elements.liveLabel.textContent = liveStatusLabel();
    elements.eventList.innerHTML = "";
    elements.playerTable.innerHTML = "";
    elements.traceSummary.textContent = "-";
    elements.agentLogSummary.textContent = "-";
    elements.liveAgentStatus.innerHTML = "";
    elements.agentLog.innerHTML = "";
    updateReportLink();
    drawEmptyField();
    return;
  }

  elements.playerSelect.value = selectedPlayer;
  const disc = state.disc;
  elements.frameLabel.textContent = `${state.frame} / ${Math.max(replay.frames.length - 1, 0)}`;
  elements.possessionLabel.textContent = state.possession_team ?? "-";
  const discText = discLabel(disc);
  const fullDiscText = fullDiscLabel(disc);
  elements.discLabel.textContent = discText;
  elements.discLabel.title = fullDiscText;
  elements.passLabel.textContent = passLabel(state.pending_pass);
  elements.stallLabel.textContent = state.stall?.active
    ? stallLabel(state.stall)
    : "inactive";
  elements.statusLabel.textContent = replay.end?.score_team
    ? `${replay.end.score_team} scored`
    : replay.end?.stop_reason ?? (state.stopped ? state.stop_reason : replay.source);
  elements.liveLabel.textContent = liveStatusLabel();

  drawField(state);
  renderSelectedPlayer(frame);
  renderEvents(frame);
  renderPlayerTable(state);
  renderTraceSummary();
  renderAgentLog(frame);
  updateReportLink();
}

function drawEmptyField() {
  const svg = elements.fieldSvg;
  clearSvg(svg);
  drawFieldBase(svg);
}

function drawField(state) {
  const svg = elements.fieldSvg;
  clearSvg(svg);
  drawFieldBase(svg);
  drawTrails(svg);
  drawFuturePath(svg, state);
  drawPlayers(svg, state);
  drawDisc(svg, state);
}

function clearSvg(svg) {
  while (svg.lastChild && svg.lastChild.nodeName !== "title") {
    svg.removeChild(svg.lastChild);
  }
}

function drawFieldBase(svg) {
  append(svg, "rect", {
    x: 0,
    y: 0,
    width: FIELD.width - 1,
    height: FIELD.height - 1,
    fill: "var(--field)",
    stroke: "#56675f",
    "stroke-width": 0.45
  });
  append(svg, "rect", {
    x: 0,
    y: 0,
    width: FIELD.leftEndZoneMax,
    height: FIELD.height - 1,
    fill: "var(--left-zone)",
    opacity: 0.85
  });
  append(svg, "rect", {
    x: FIELD.rightEndZoneMin,
    y: 0,
    width: FIELD.width - FIELD.rightEndZoneMin - 1,
    height: FIELD.height - 1,
    fill: "var(--right-zone)",
    opacity: 0.85
  });
  for (let x = 1; x < FIELD.width - 1; x += 1) {
    append(svg, "line", {
      x1: x,
      y1: 0,
      x2: x,
      y2: FIELD.height - 1,
      stroke: "#a8b3ad",
      "stroke-width": 0.045,
      opacity: 0.38
    });
  }
  for (let y = 1; y < FIELD.height - 1; y += 1) {
    append(svg, "line", {
      x1: 0,
      y1: y,
      x2: FIELD.width - 1,
      y2: y,
      stroke: "#a8b3ad",
      "stroke-width": 0.045,
      opacity: 0.38
    });
  }
  append(svg, "line", {
    x1: FIELD.leftEndZoneMax,
    y1: 0,
    x2: FIELD.leftEndZoneMax,
    y2: FIELD.height - 1,
    stroke: "#5a7068",
    "stroke-width": 0.55,
    "stroke-dasharray": "2 1.5"
  });
  append(svg, "line", {
    x1: FIELD.rightEndZoneMin,
    y1: 0,
    x2: FIELD.rightEndZoneMin,
    y2: FIELD.height - 1,
    stroke: "#5a7068",
    "stroke-width": 0.55,
    "stroke-dasharray": "2 1.5"
  });
  append(svg, "line", {
    x1: 101,
    y1: 0,
    x2: 101,
    y2: FIELD.height - 1,
    stroke: "#7e918b",
    "stroke-width": 0.3,
    "stroke-dasharray": "1.5 1.5"
  });

  for (let x = 10; x < FIELD.width; x += 10) {
    append(svg, "line", {
      x1: x,
      y1: 0,
      x2: x,
      y2: FIELD.height - 1,
      stroke: "#77847e",
      "stroke-width": 0.09,
      opacity: 0.55
    });
  }
  for (let y = 10; y < FIELD.height; y += 10) {
    append(svg, "line", {
      x1: 0,
      y1: y,
      x2: FIELD.width - 1,
      y2: y,
      stroke: "#77847e",
      "stroke-width": 0.09,
      opacity: 0.55
    });
  }

  label(svg, 18, -1.8, "left end zone", "#164d9a", 3);
  label(svg, 101, -1.8, "central field", "#45564f", 3);
  label(svg, 183, -1.8, "right end zone", "#9d2926", 3);
  label(svg, 15, 76.5, "red attacks -x", "#9d2926", 2.8);
  label(svg, 183, 76.5, "blue attacks +x", "#164d9a", 2.8);
}

function drawTrails(svg) {
  const frames = replay.frames.slice(Math.max(0, frameIndex - 6), frameIndex + 1);
  const selectedPoints = frames
    .map((frame) => frame.state?.players?.[selectedPlayer])
    .filter(Boolean)
    .map((player) => `${player.x},${player.y}`)
    .join(" ");
  if (selectedPoints.includes(" ")) {
    append(svg, "polyline", {
      points: selectedPoints,
      fill: "none",
      stroke: "var(--selected)",
      "stroke-width": 0.7,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      opacity: 0.7
    });
  }

  const discPoints = frames
    .map((frame) => frame.state?.disc)
    .filter(Boolean)
    .map((disc) => `${disc.x},${disc.y}`)
    .join(" ");
  if (discPoints.includes(" ")) {
    append(svg, "polyline", {
      points: discPoints,
      fill: "none",
      stroke: "var(--disc-dark)",
      "stroke-width": 0.65,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "stroke-dasharray": "1.4 1",
      opacity: 0.8
    });
  }
}

function drawFuturePath(svg, state) {
  const disc = state.disc;
  const path = disc?.future_path;
  if (!disc || !Array.isArray(path) || path.length === 0) return;
  const points = [`${disc.x},${disc.y}`, ...path.map((point) => `${point.x},${point.y}`)].join(" ");
  append(svg, "polyline", {
    points,
    fill: "none",
    stroke: "var(--disc-dark)",
    "stroke-width": 0.75,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "stroke-dasharray": "2.2 1.2",
    opacity: 0.92
  });
  for (const point of path) {
    append(svg, "circle", {
      cx: point.x,
      cy: point.y,
      r: point.in_bounds === false ? 0.72 : 0.52,
      fill: point.in_bounds === false ? "var(--red)" : "var(--disc)",
      stroke: "var(--disc-dark)",
      "stroke-width": 0.18,
      opacity: 0.92
    });
  }
}

function drawPlayers(svg, state) {
  const players = state.players ?? {};
  const frame = currentFrame();
  for (const [playerId, player] of Object.entries(players)) {
    const teamColor = player.team === "blue" ? "var(--blue)" : "var(--red)";
    const teamStroke = player.team === "blue" ? "var(--blue-dark)" : "var(--red-dark)";
    const runtime = playerRuntimeState(playerId, frame);
    const group = append(svg, "g", {
      class: [
        "svg-player",
        runtime.className,
        playerId === selectedPlayer ? "selected" : ""
      ].filter(Boolean).join(" "),
      "data-player": playerId
    });
    group.addEventListener("click", () => {
      selectedPlayer = playerId;
      elements.playerSelect.value = playerId;
      render();
    });
    append(group, "title").textContent = `${playerId}: ${runtime.detail}`;
    if (runtime.kind !== "none") {
      append(group, "circle", {
        class: "runtime-ring",
        cx: player.x,
        cy: player.y,
        r: 1.85
      });
    }
    append(group, "circle", {
      class: "player-dot",
      cx: player.x,
      cy: player.y,
      r: player.has_disc ? 1.5 : 1.28,
      fill: teamColor,
      stroke: player.has_disc ? "var(--disc-dark)" : teamStroke
    });
    if (playerId === selectedPlayer) {
      append(group, "circle", {
        class: "selected-marker",
        cx: player.x + 1.72,
        cy: player.y > 2.5 ? player.y - 1.72 : player.y + 1.72,
        r: 0.48
      });
    }
    append(group, "text", {
      class: "svg-label",
      x: player.x,
      y: player.y + 0.05
    }).textContent = shortPlayerLabel(playerId);
  }
}

function drawDisc(svg, state) {
  const disc = state.disc;
  if (!disc) return;
  const holder = disc.holder ? state.players?.[disc.holder] : null;
  const x = holder ? holder.x + 1.25 : disc.x;
  const y = holder ? holder.y - 1.55 : disc.y;
  append(svg, "circle", {
    cx: x,
    cy: y,
    r: disc.holder ? 0.75 : 0.95,
    fill: "var(--disc)",
    stroke: "var(--disc-dark)",
    "stroke-width": 0.28
  });
  append(svg, "ellipse", {
    cx: x,
    cy: y,
    rx: disc.holder ? 1.05 : 1.25,
    ry: disc.holder ? 0.45 : 0.58,
    fill: "none",
    stroke: "#ffd37a",
    "stroke-width": 0.28
  });
}

function playerRuntimeState(playerId, frame) {
  if (!frame || frame.type === "initial") {
    return { kind: "none", className: "", label: "", detail: "not evaluated" };
  }
  const awakeSleep = frame.awake_sleep;
  const modelCalled = (frame.model_results ?? []).some((result) => result.player_id === playerId);
  if (awakeSleep?.awake_players?.includes(playerId) || modelCalled) {
    const reason = awakeSleep?.wake_reasons_by_player?.[playerId];
    return {
      kind: "awake",
      className: "runtime-awake",
      detail: reason ? `awake (${reason.replaceAll("_", " ")})` : "awake"
    };
  }
  if (awakeSleep?.sleeping_players?.includes(playerId)) {
    const intent = awakeSleep?.controller?.stored_intents?.[playerId];
    const frames = intent?.frames_remaining != null ? `, ${intent.frames_remaining}f left` : "";
    return {
      kind: "intent",
      className: "runtime-intent",
      detail: `intent${frames}`
    };
  }
  return { kind: "none", className: "", label: "", detail: "idle" };
}

function renderSelectedPlayer(frame) {
  const state = frame.state;
  const player = state.players?.[selectedPlayer];
  if (!player) {
    elements.playerPosition.textContent = "-";
    elements.playerRole.textContent = "-";
    elements.playerMatchup.textContent = "-";
    elements.playerAttributes.textContent = "-";
    elements.playerAction.textContent = "-";
    elements.playerReason.textContent = "-";
    return;
  }

  const action = frame.actions?.[selectedPlayer];
  elements.playerPosition.textContent = `(${player.x}, ${player.y})${player.has_disc ? " with disc" : ""}`;
  elements.playerRole.textContent = roleLabel(selectedPlayer, state);
  elements.playerMatchup.textContent = matchupFor(selectedPlayer) ?? "-";
  elements.playerAttributes.textContent = [
    `height ${player.height}`,
    `speed ${player.speed}`,
    `throw ${player.throw}`,
    `max move ${player.max_move_cells}`
  ].join(", ");
  elements.playerAction.textContent = action ? actionLabel(action) : "-";
  elements.playerReason.textContent = action?.reason ?? "-";
}

function renderEvents(frame) {
  const events = frame.events ?? [];
  elements.eventList.innerHTML = "";
  if (!events.length) {
    const item = document.createElement("li");
    item.textContent = "Initial state";
    elements.eventList.append(item);
    return;
  }
  for (const event of events) {
    const item = document.createElement("li");
    item.textContent = eventLabel(event);
    elements.eventList.append(item);
  }
}

function renderPlayerTable(state) {
  const players = state.players ?? {};
  const frame = currentFrame();
  elements.playerTable.innerHTML = "";
  for (const playerId of Object.keys(players).sort()) {
    const player = players[playerId];
    const runtime = playerRuntimeState(playerId, frame);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = [
      "player-chip",
      runtime.className,
      playerId === selectedPlayer ? "selected" : ""
    ].filter(Boolean).join(" ");
    chip.addEventListener("click", () => {
      selectedPlayer = playerId;
      elements.playerSelect.value = playerId;
      render();
    });
    const title = document.createElement("strong");
    title.innerHTML = `<span>${playerId}</span><span>${roleLabel(playerId, state)}</span>`;
    const details = document.createElement("span");
    details.textContent = [
      runtime.kind !== "none" ? runtime.detail : null,
      `vs ${matchupFor(playerId)}`,
      `(${player.x}, ${player.y})`,
      `H${player.height}`,
      `S${player.speed}`,
      `T${player.throw}`,
      `M${player.max_move_cells}`,
      player.has_disc ? "disc" : null,
      state.pending_pass?.intended_receiver === playerId ? "eye contact" : null
    ].filter(Boolean).join(" ");
    chip.append(title, details);
    elements.playerTable.append(chip);
  }
}

function renderTraceSummary() {
  const frame = currentFrame();
  if (!frame) {
    elements.traceSummary.textContent = "-";
    return;
  }
  const discEvents = (frame.events ?? []).filter((event) =>
    [
      "pass_intent",
      "committed_throw_forced",
      "throw_released",
      "disc_flying",
      "catch",
      "defensive_block",
      "turnover",
      "disc_out_of_bounds"
    ].includes(event.type)
  );
  if (!discEvents.length) {
    elements.traceSummary.textContent = "No disc event in this frame.";
    return;
  }
  elements.traceSummary.textContent = discEvents.map(eventLabel).join(" ");
}

function renderAgentLog(frame) {
  renderLiveAgentStatus();
  elements.agentLog.innerHTML = "";
  const results = [...(frame.model_results ?? [])].sort(compareModelResults);
  const usage = frame.usage ? usageSummary(frame.usage) : "no usage";
  const wall = frame.wall_seconds ? `${frame.wall_seconds}s batch` : "no batch";
  const awakeSleep = frame.awake_sleep;
  const sleepSummary = awakeSleep
    ? `${awakeSleep.awake_players?.length ?? 0} awake, ${awakeSleep.sleeping_players?.length ?? 0} sleeping`
    : null;
  elements.agentLogSummary.textContent = results.length
    ? `${results.length} agent responses, ${sleepSummary ? `${sleepSummary}, ` : ""}${wall}, ${usage}`
    : liveStatus?.running
      ? "waiting for current API batch"
      : sleepSummary ?? "no model responses on this frame";

  if (!results.length) {
    const empty = document.createElement("p");
    empty.className = "trace-summary";
    empty.textContent = frame.type === "initial"
      ? "Initial state has no agent calls."
      : sleepSummary
        ? `${sleepSummary}; controller filled sleeping actions.`
        : "No model responses recorded.";
    elements.agentLog.append(empty);
  } else {
    for (const result of results) {
      elements.agentLog.append(agentCard(result));
    }
  }

  if (awakeSleep?.controller?.action_sources) {
    elements.agentLog.append(controllerSummary(awakeSleep));
  }
}

function renderLiveAgentStatus() {
  elements.liveAgentStatus.innerHTML = "";
  const statuses = liveStatus?.agent_call_status ?? {};
  const entries = Object.entries(statuses).sort(([left], [right]) => left.localeCompare(right));
  if (!entries.length) return;

  for (const [playerId, status] of entries) {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = `live-agent-pill ${status.state ?? "queued"}`;
    pill.addEventListener("click", () => {
      selectedPlayer = playerId;
      elements.playerSelect.value = playerId;
      render();
    });

    const title = document.createElement("strong");
    const name = document.createElement("span");
    name.textContent = playerId;
    const state = document.createElement("span");
    state.textContent = status.state ?? "queued";
    title.append(name, state);

    const detail = document.createElement("span");
    const elapsed = status.elapsed_seconds != null ? `${status.elapsed_seconds}s` : "-";
    const action = status.action ? `, ${status.action}` : "";
    detail.textContent = `frame ${status.frame ?? "-"}, ${elapsed}${action}`;
    pill.append(title, detail);
    elements.liveAgentStatus.append(pill);
  }
}

function agentCard(result) {
  const card = document.createElement("article");
  const playerId = result.player_id ?? "-";
  card.className = `agent-card${playerId === selectedPlayer ? " selected" : ""}${result.ok ? "" : " error"}`;
  card.addEventListener("click", () => {
    selectedPlayer = playerId;
    elements.playerSelect.value = playerId;
    render();
  });

  const heading = document.createElement("h3");
  const name = document.createElement("span");
  name.textContent = playerId;
  const status = document.createElement("span");
  status.textContent = result.ok ? "ok" : "error";
  heading.append(name, status);

  const action = result.action ?? {};
  const statusRow = document.createElement("div");
  statusRow.className = "status-row";
  for (const text of [
    action.action ?? "-",
    `${result.latency_seconds ?? "-"}s`,
    result.finish_reason ? `finish ${result.finish_reason}` : null
  ].filter(Boolean)) {
    statusRow.append(statusChip(text));
  }

  const metricRow = document.createElement("div");
  metricRow.className = "metric-row";
  for (const text of [
    actionLabel(action),
    usageSummary(result.usage ?? {}),
    result.usage?.prompt_cache_hit_tokens ? `${result.usage.prompt_cache_hit_tokens} cached` : null
  ].filter(Boolean)) {
    metricRow.append(statusChip(text));
  }

  card.append(heading, statusRow, metricRow);
  const reason = document.createElement("p");
  reason.textContent = action.reason ?? result.error ?? "No agent reason recorded.";
  card.append(reason);

  if (result.error) {
    const error = document.createElement("p");
    error.textContent = result.error;
    card.append(error);
  }
  if (result.reasoning_content) {
    card.append(detailsBlock("Returned thinking trace", result.reasoning_content));
  }
  if (result.raw_content) {
    card.append(detailsBlock("Raw model content", result.raw_content));
  }
  return card;
}

function controllerSummary(awakeSleep) {
  const details = document.createElement("details");
  details.className = "controller-summary";
  const summary = document.createElement("summary");
  const awake = awakeSleep.awake_players?.length ?? 0;
  const sleeping = awakeSleep.sleeping_players?.length ?? 0;
  summary.textContent = `V2 controller: ${awake} awake, ${sleeping} sleeping`;
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify({
    wake_reasons_by_player: awakeSleep.wake_reasons_by_player,
    action_sources: awakeSleep.controller?.action_sources,
    stored_intents: awakeSleep.controller?.stored_intents
  }, null, 2);
  details.append(summary, pre);
  return details;
}

function statusChip(text) {
  const chip = document.createElement("span");
  chip.textContent = text;
  return chip;
}

function detailsBlock(summaryText, bodyText) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = summaryText;
  const pre = document.createElement("pre");
  pre.textContent = bodyText;
  details.append(summary, pre);
  return details;
}

function compareModelResults(left, right) {
  return (left.player_id ?? "").localeCompare(right.player_id ?? "");
}

function usageSummary(usage) {
  const total = usage.total_tokens ?? "-";
  const completion = usage.completion_tokens ?? "-";
  return `${total} tokens, ${completion} out`;
}

function updateReportLink() {
  const enabled = Boolean(liveStatus?.log_path || liveStatus?.report_path);
  elements.reportLink.setAttribute("aria-disabled", enabled ? "false" : "true");
  elements.reportLink.style.pointerEvents = enabled ? "auto" : "none";
  elements.reportLink.style.opacity = enabled ? "1" : "0.55";
}

function eventLabel(event) {
  switch (event.type) {
    case "movement":
      return `${event.player} moved to (${event.to.x}, ${event.to.y})`;
    case "movement_lost_collision":
      return `${event.player} lost collision at (${event.target.x}, ${event.target.y}) to ${event.winner}`;
    case "movement_blocked":
      return `${event.player} was blocked by ${event.by}`;
    case "pass_intent":
      return `${event.thrower} made eye contact with ${event.intended_receiver}; release frame ${event.release_frame}`;
    case "committed_throw_forced":
      return `${event.thrower} was forced to release committed pass to ${event.intended_receiver}`;
    case "throw_released":
      return `${event.thrower} threw ${event.throw_side} toward (${event.target.x}, ${event.target.y})`;
    case "disc_flying":
      return `disc flew from (${fmt(event.from.x)}, ${fmt(event.from.y)}) to (${fmt(event.to.x)}, ${fmt(event.to.y)})`;
    case "catch":
      return `${event.player} caught the disc${discContactLabel(event)}`;
    case "defensive_block":
      return `${event.player} blocked the disc${discContactLabel(event)}`;
    case "turnover":
      return `turnover: ${event.reason}, new thrower ${event.new_thrower}`;
    case "stall_count":
      return `stall ${event.count}${event.limit ? `/${event.limit}` : ""} on ${event.thrower}${event.remaining != null ? `, ${event.remaining} left` : ""}`;
    case "score":
      return `${event.team} scored`;
    case "disc_out_of_bounds":
      if (event.restart_spot) {
        const crossing = event.crossing ? `crossed at (${fmt(event.crossing.x)}, ${fmt(event.crossing.y)})` : `went out at (${fmt(event.at.x)}, ${fmt(event.at.y)})`;
        return `disc ${crossing}; ${event.restart_player ?? "new thrower"} restarts at (${event.restart_spot.x}, ${event.restart_spot.y})`;
      }
      return `disc went out at (${fmt(event.at.x)}, ${fmt(event.at.y)})`;
    case "throw_release_failed":
      return `${event.marker} blocked ${event.thrower} at release`;
    case "public_call":
      return `${event.player} called ${event.message}`;
    case "public_message":
      return `${event.player}: ${event.message}`;
    default:
      return event.type.replaceAll("_", " ");
  }
}

function discContactLabel(event) {
  if (!event.at) return "";
  const progress = event.progress != null ? `, t=${fmt(event.progress)}` : "";
  return ` at (${fmt(event.at.x)}, ${fmt(event.at.y)}${progress})`;
}

function actionLabel(action) {
  if (action.action === "move_intent" && action.target) {
    return `intent to (${action.target.x}, ${action.target.y}) for ${action.duration_frames ?? "-"}f`;
  }
  if (action.action === "move" && action.target) {
    return `move to (${action.target.x}, ${action.target.y})`;
  }
  if (action.action === "signal_throw") {
    return `eye contact with ${action.intended_receiver ?? "-"}`;
  }
  if (action.action === "throw" && action.target) {
    return `throw ${action.throw_side} to (${action.target.x}, ${action.target.y})`;
  }
  if (action.action === "talk" || action.action === "call_stack") {
    return `${action.action}: ${action.message ?? ""}`;
  }
  return action.action;
}

function matchupFor(playerId) {
  if (FIXED_MATCHUPS[playerId]) return FIXED_MATCHUPS[playerId];
  for (const [blueId, redId] of Object.entries(FIXED_MATCHUPS)) {
    if (redId === playerId) return blueId;
  }
  return null;
}

function roleLabel(playerId, state) {
  const player = state?.players?.[playerId];
  if (!player) return "-";
  const holder = state.disc?.holder;
  const pending = state.pending_pass;
  if (pending?.thrower === playerId) return "committed thrower";
  if (pending?.intended_receiver === playerId) return "intended receiver";
  if (holder === playerId) return "thrower";
  if (state.possession_team === player.team) return "offense";
  if (holder && matchupFor(holder) === playerId) return "marker";
  return "defense";
}

function discLabel(disc) {
  if (!disc) return "-";
  if (disc.holder) return `held by ${disc.holder}`;
  const speed = disc.speed != null ? ` v${fmt(disc.speed)}` : "";
  return `flying (${fmt(disc.x)}, ${fmt(disc.y)})${speed}`;
}

function fullDiscLabel(disc) {
  if (!disc) return "-";
  if (disc.holder) return `held by ${disc.holder}`;
  const velocity = disc.velocity ? ` velocity=(${fmt(disc.velocity.x)}, ${fmt(disc.velocity.y)})` : "";
  const speed = disc.speed != null ? ` speed=${fmt(disc.speed)}` : "";
  return `flying at (${fmt(disc.x)}, ${fmt(disc.y)})${velocity}${speed}`;
}

function passLabel(pendingPass) {
  if (!pendingPass) return "none";
  const receiver = pendingPass.intended_receiver ?? pendingPass.intended_receiver_visible_to_you ?? "-";
  return `${pendingPass.thrower ?? "-"} -> ${receiver}, f${pendingPass.release_frame ?? "-"}`;
}

function stallLabel(stall) {
  const count = stall.count ?? 0;
  if (stall.limit == null) {
    return `${count} on ${stall.thrower ?? "-"}`;
  }
  const limit = stall.limit;
  const remaining = stall.remaining != null ? `${stall.remaining} left` : `${count}/${limit}`;
  return `${remaining} (${count}/${limit}) on ${stall.thrower ?? "-"}`;
}

function firstPlayerId(state) {
  return Object.keys(state?.players ?? {})[0] ?? null;
}

function shortPlayerLabel(playerId) {
  const [team, number] = playerId.split("_");
  return `${team[0].toUpperCase()}${number}`;
}

function fmt(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function append(parent, tag, attrs = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, String(value));
  }
  parent.append(element);
  return element;
}

function label(svg, x, y, text, fill, size) {
  append(svg, "text", {
    x,
    y,
    fill,
    "font-size": size,
    "font-weight": 800,
    "text-anchor": "middle"
  }).textContent = text;
}

function stopPlayback() {
  clearInterval(timer);
  timer = null;
  elements.playToggle.textContent = "Play";
}

function togglePlayback() {
  if (timer) {
    stopPlayback();
    return;
  }
  elements.playToggle.textContent = "Pause";
  timer = setInterval(() => {
    if (frameIndex >= replay.frames.length - 1) {
      stopPlayback();
      return;
    }
    frameIndex += 1;
    render();
  }, Number(elements.speedSelect.value));
}

elements.loadSample.addEventListener("click", () => {
  loadSampleReplay().catch((error) => {
    elements.statusLabel.textContent = error.message;
  });
});

elements.startLive.addEventListener("click", () => {
  startLiveTrial().catch((error) => {
    elements.liveLabel.textContent = error.message;
  });
});

elements.stopLive.addEventListener("click", () => {
  stopLiveTrial().catch((error) => {
    elements.liveLabel.textContent = error.message;
  });
});

elements.configLockToggle.addEventListener("click", () => {
  configurationLocked = !configurationLocked;
  updateConfigurationLock();
});

elements.fileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  parseJsonl(await file.text(), file.name);
});

elements.prevFrame.addEventListener("click", () => {
  stopPlayback();
  frameIndex = Math.max(0, frameIndex - 1);
  render();
});

elements.nextFrame.addEventListener("click", () => {
  stopPlayback();
  frameIndex = Math.min(Math.max(replay.frames.length - 1, 0), frameIndex + 1);
  render();
});

elements.playToggle.addEventListener("click", togglePlayback);
elements.timeline.addEventListener("input", (event) => {
  stopPlayback();
  frameIndex = Number(event.target.value);
  render();
});

elements.speedSelect.addEventListener("change", () => {
  if (timer) {
    stopPlayback();
    togglePlayback();
  }
});

elements.playerSelect.addEventListener("change", (event) => {
  selectedPlayer = event.target.value;
  render();
});

updateConfigurationLock();
drawEmptyField();
loadSampleReplay().catch((error) => {
  elements.statusLabel.textContent = error.message;
});
startLivePolling();

async function startLiveTrial() {
  const maxFrames = boundedNumber(elements.maxFramesInput.value, 20, 1, 50);
  const response = await fetch("/api/trial/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      game_version: elements.gameVersionSelect.value,
      model: elements.modelSelect.value,
      thinking: elements.thinkingSelect.value,
      max_frames: maxFrames,
      max_api_calls: maxFrames * 10,
      history_frames: 4,
      throw_score_override: boundedNumber(elements.throwScoreSelect.value, 100, 0, 100),
      max_disc_speed_override: boundedNumber(elements.discSpeedInput.value, 18, 0, 30),
      max_estimated_usd: 1.0,
      seed: 7
    })
  });
  if (!response.ok) throw new Error("Live server unavailable");
  const payload = await response.json();
  if (!payload.ok) throw new Error(payload.error || "Could not start live trial");
  liveStatus = payload.status;
  elements.liveLabel.textContent = liveStatusLabel();
  await loadLiveReplay({followLatest: true});
}

async function stopLiveTrial() {
  const response = await fetch("/api/trial/stop", {method: "POST"});
  if (!response.ok) throw new Error("Live server unavailable");
  const payload = await response.json();
  liveStatus = payload.status;
  elements.liveLabel.textContent = liveStatusLabel();
}

function startLivePolling() {
  if (livePollTimer) clearInterval(livePollTimer);
  pollLiveStatus().catch(() => {
    elements.liveLabel.textContent = "static viewer";
  });
  livePollTimer = setInterval(() => {
    pollLiveStatus().catch(() => {
      elements.liveLabel.textContent = "static viewer";
    });
  }, 1800);
}

async function pollLiveStatus() {
  const response = await fetch("/api/trial/status", {cache: "no-store"});
  if (!response.ok) throw new Error("Live controls unavailable");
  liveStatus = await response.json();
  elements.liveLabel.textContent = liveStatusLabel();
  elements.startLive.disabled = Boolean(liveStatus.running);
  elements.stopLive.disabled = !liveStatus.running;
  updateReportLink();
  if (liveStatus.log_path || liveStatus.running) {
    await loadLiveReplay({preserveIndex: true});
  } else {
    render();
  }
}

async function loadLiveReplay(options = {}) {
  const response = await fetch("/api/trial/replay", {cache: "no-store"});
  if (!response.ok) return;
  const text = await response.text();
  if (!text.trim()) return;
  parseJsonl(text, "deepseek_v2_live_latest.jsonl", options);
}

function liveStatusLabel() {
  if (!liveStatus) return "not connected";
  const version = liveStatus.game_version === "v2_awake_sleep" ? "v2" : "v1";
  if (liveStatus.running) {
    const thinking = Object.values(liveStatus.agent_call_status ?? {}).filter((status) => status.state === "thinking").length;
    const suffix = thinking ? `, ${thinking} thinking` : "";
    const sleeping = Object.values(liveStatus.agent_call_status ?? {}).filter((status) => status.state === "sleeping").length;
    const sleepSuffix = sleeping ? `, ${sleeping} sleeping` : "";
    return `${version} running frame ${liveStatus.frame}/${liveStatus.max_frames}${suffix}${sleepSuffix}, $${Number(liveStatus.estimated_cost_usd || 0).toFixed(4)}`;
  }
  if (liveStatus.stop_reason) {
    return `${version} ${liveStatus.stop_reason}, $${Number(liveStatus.estimated_cost_usd || 0).toFixed(4)}`;
  }
  if (liveStatus.log_path) return "ready";
  return "idle";
}

function boundedNumber(value, fallback, low, high) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(Math.max(Math.trunc(number), low), high);
}
