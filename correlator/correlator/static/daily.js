"use strict";

// Daily Summary: one day's Clips on a timeline, the chosen Clip in the player, and the panel
// where each Press is given its Review Decision.

const DAY_SECONDS = 86400;
const DAY_REFRESH_MS = 15000;
const MIN_VIEW_SECONDS = 60;
const CLICK_REACH_PX = 14;
const LANES = ["cat", "human", "ambiguous"];
// After the page appears, how long and how often it asks whether an Utterance Alert's
// "Open Clip" button wants one Clip shown. The button's message can arrive after the page does.
const OPEN_CLIP_WATCH_MS = 10000;
const OPEN_CLIP_POLL_MS = 1000;
const HOUR_LABEL_SPACING = 44; // fewest pixels between the centres of two hour labels

const state = {
  day: null, // the reply of api/days/<date>
  exchangeId: null,
  pressId: null,
  view: { start: 0, end: DAY_SECONDS }, // the stretch of the day the timeline shows, in seconds from midnight
  subtab: "clip",
  movePlayhead: () => {},
  pendingSeek: null,
};

const video = $("video");
const canvas = $("day-canvas");

// ---- Loading ------------------------------------------------------------------

async function loadDay(day, keepSelection) {
  let data;
  try {
    data = await api(`api/days/${day}`);
    clearProblem();
  } catch (error) {
    showProblem(error);
    return;
  }
  const changedDay = !state.day || state.day.date !== data.date;
  state.day = data;
  if (changedDay) state.view = { start: 0, end: DAY_SECONDS };

  $("day-picker").value = data.date;
  $("day-picker").min = data.first_day;
  $("day-picker").max = data.today;
  $("day-previous").disabled = data.date <= data.first_day;
  $("day-next").disabled = data.date >= data.today;
  $("day-title").textContent = `${dayName(data.date)} · ${plural(data.exchanges.length, "Clip")}`;

  const stillThere = keepSelection && data.exchanges.some((exchange) => exchange.id === state.exchangeId);
  if (stillThere) {
    renderClip(false);
  } else {
    const wanted = keepSelection ? null : new URLSearchParams(location.search);
    const fromLink = wanted && data.exchanges.find((exchange) => String(exchange.id) === wanted.get("clip"));
    const latest = data.exchanges[data.exchanges.length - 1];
    selectExchange((fromLink || latest || {}).id || null, fromLink ? Number(wanted.get("press")) || null : null);
  }
  renderDayPanel();
  drawDay();
}

function goToDay(day) {
  history.replaceState(null, "", `?day=${day}`);
  state.exchangeId = null;
  loadDay(day, true);
}

function currentExchange() {
  return state.day ? state.day.exchanges.find((exchange) => exchange.id === state.exchangeId) || null : null;
}

function currentPress() {
  const exchange = currentExchange();
  return exchange ? exchange.presses.find((press) => press.id === state.pressId) || null : null;
}

// ---- The chosen Clip ----------------------------------------------------------

function selectExchange(exchangeId, pressId) {
  state.exchangeId = exchangeId;
  const exchange = currentExchange();
  state.pressId = exchange ? pressId || exchange.presses[0].id : null;
  renderClip(true);
  if (exchange && pressId) seekToPress(exchange.presses.find((press) => press.id === pressId));
  renderDayPanel();
  drawDay();
}

function selectPress(press, seek) {
  state.pressId = press.id;
  if (seek) seekToPress(press);
  renderClip(false);
}

function seekToPress(press) {
  const exchange = currentExchange();
  const offset = press && exchange ? clipOffset(exchange, press) : null;
  if (offset === null) return;
  // A little before the Press, so the approach to the button is seen.
  seekTo(Math.max(offset - 1, 0));
}

function seekTo(seconds) {
  if (video.hidden) return;
  if (video.readyState >= 1) {
    video.currentTime = seconds;
  } else {
    state.pendingSeek = seconds;
  }
}

function renderClip(newClip) {
  const exchange = currentExchange();
  if (newClip) {
    state.pendingSeek = null;
    if (exchange && exchange.clip_url) {
      video.src = exchange.clip_url;
      video.hidden = false;
      $("player-message").hidden = true;
    } else {
      video.removeAttribute("src");
      video.load();
      video.hidden = true;
      $("player-message").hidden = false;
      $("player-message").textContent = exchange ? clipStatusText(exchange) : emptyDayText();
    }
  } else if (exchange && exchange.clip_url && video.hidden) {
    // The Clip became ready while it was being looked at.
    renderClip(true);
    return;
  }

  const timeline = $("clip-timeline");
  if (!exchange) {
    timeline.replaceChildren(element("p", "empty", "No Clip chosen."));
    $("clip-title").textContent = "Clip";
    state.movePlayhead = () => {};
  } else {
    $("clip-title").textContent = `Clip at ${clockTime(exchange.started_at)}`;
    state.movePlayhead = drawClipTimeline(timeline, exchange, {
      selectedPressId: state.pressId,
      onSeek: seekTo,
      onPress: (press) => selectPress(press, true),
    });
    state.movePlayhead(video.currentTime || 0);
  }
  renderClipPanel();
}

function emptyDayText() {
  if (!state.day) return "Loading…";
  return state.day.observed.length
    ? "No Presses were recorded on this day."
    : "Nothing was observed on this day.";
}

// ---- Review Decisions ---------------------------------------------------------

async function decide(press, decision) {
  try {
    await sendReview("presses", press.id, decision);
    await loadDay(state.day.date, true);
  } catch (error) {
    showProblem(error);
  }
}

async function decideWholeClip(decision) {
  try {
    await sendReview("exchanges", state.exchangeId, decision);
    await loadDay(state.day.date, true);
  } catch (error) {
    showProblem(error);
  }
}

function stepPress(step) {
  const exchange = currentExchange();
  if (!exchange) return;
  const index = exchange.presses.findIndex((press) => press.id === state.pressId);
  const next = exchange.presses[index + step];
  if (next) selectPress(next, true);
}

function stepClip(step) {
  const exchanges = state.day ? state.day.exchanges : [];
  const index = exchanges.findIndex((exchange) => exchange.id === state.exchangeId);
  const next = exchanges[index + step];
  if (next) selectExchange(next.id, null);
}

// ---- Panel: Clip --------------------------------------------------------------

function decisionButtons(current, onDecide) {
  const row = element("div", "decisions");
  for (const [decision, label] of Object.entries(DECISION_LABELS)) {
    const button = element("button", decision, label);
    if (current === decision) button.classList.add("chosen");
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      onDecide(current === decision ? null : decision);
    });
    row.appendChild(button);
  }
  if (current) {
    const undo = element("button", "undo", "Undo");
    undo.title = "Withdraw this Review Decision";
    undo.addEventListener("click", (event) => {
      event.stopPropagation();
      onDecide(null);
    });
    row.appendChild(undo);
  }
  return row;
}

function renderClipPanel() {
  const panel = $("subtab-clip");
  const exchange = currentExchange();
  panel.replaceChildren();
  if (!exchange) {
    panel.appendChild(element("p", "empty", "Pick a Clip from the timeline or the Day list."));
    return;
  }

  const head = element("div", "panel-head");
  head.appendChild(element("h3", "", `${clockTime(exchange.started_at)} – ${clockTime(exchange.ended_at)}`));
  head.appendChild(
    element(
      "p",
      "hint",
      `${plural(exchange.presses.length, "Press", "Presses")} in ${plural(exchange.utterances.length, "Utterance")}`,
    ),
  );
  if (!exchange.clip_url) head.appendChild(element("p", "hint", clipStatusText(exchange)));
  panel.appendChild(head);

  if (exchange.presses.length > 1) {
    const whole = element("div", "whole-clip");
    whole.appendChild(element("span", "hint", "Set the whole Clip to"));
    const everyDecision = exchange.presses.every(
      (press) => press.review_decision === exchange.presses[0].review_decision,
    )
      ? exchange.presses[0].review_decision
      : null;
    whole.appendChild(decisionButtons(everyDecision, decideWholeClip));
    panel.appendChild(whole);
  }

  const pressesById = new Map(exchange.presses.map((press) => [press.id, press]));
  const shown = new Set();
  for (const utterance of exchange.utterances) {
    const group = element("div", `utterance-group ${utterance.presser}`);
    group.appendChild(
      element(
        "div",
        "utterance-label",
        `${PRESSER_LABELS[utterance.presser]} Utterance · ${plural(utterance.words.length, "Word")}`,
      ),
    );
    for (const pressId of utterance.press_ids) {
      group.appendChild(pressRow(exchange, pressesById.get(pressId)));
      shown.add(pressId);
    }
    panel.appendChild(group);
  }
  // Discarded Presses belong to no Utterance, but must stay reachable so the decision can be undone.
  const discarded = exchange.presses.filter((press) => !shown.has(press.id));
  if (discarded.length) {
    const group = element("div", "utterance-group discarded");
    group.appendChild(element("div", "utterance-label", "Discarded · not counted"));
    for (const press of discarded) group.appendChild(pressRow(exchange, press));
    panel.appendChild(group);
  }

  panel.appendChild(
    element("p", "hint keys", "Keys: C cat · H human · D discard · U undo · ← → Press · [ ] Clip · Space play"),
  );
  const chosen = panel.querySelector(".press.selected");
  if (chosen) chosen.scrollIntoView({ block: "nearest" });
}

function pressRow(exchange, press) {
  const row = element("div", "press");
  if (press.id === state.pressId) row.classList.add("selected");
  const title = element("div", "press-title");
  title.appendChild(wordChip(press.word, press.presser, press.word_uncertain));
  const offset = clipOffset(exchange, press);
  title.appendChild(
    element("span", "press-detail", offset === null ? clockTime(press.pressed_at) : `${offset.toFixed(1)} s into the Clip`),
  );
  row.appendChild(title);

  let detail;
  if (press.review_decision) {
    detail = `Review Decision. Automatic answer: ${PRESSER_LABELS[press.automatic_presser].toLowerCase()}.`;
  } else if (press.automatic_presser === "ambiguous") {
    detail = `Awaiting review. ${AMBIGUITY_REASONS[press.ambiguity] || ""}`;
  } else {
    detail = "Automatic answer, not reviewed.";
  }
  row.appendChild(element("div", "press-detail", detail));
  row.appendChild(decisionButtons(press.review_decision, (decision) => decide(press, decision)));
  row.addEventListener("click", () => selectPress(press, true));
  return row;
}

// ---- Panel: Day ---------------------------------------------------------------

function tile(value, label) {
  const node = element("div", "tile");
  node.appendChild(element("span", "tile-value", value));
  node.appendChild(element("span", "tile-label", label));
  return node;
}

function renderDayPanel() {
  const panel = $("subtab-day");
  panel.replaceChildren();
  if (!state.day) return;
  const figures = state.day.figures;

  const tiles = element("div", "tiles");
  tiles.appendChild(tile(state.day.exchanges.length, state.day.exchanges.length === 1 ? "Clip" : "Clips"));
  tiles.appendChild(tile(figures.cat.words, "Words by the cat"));
  tiles.appendChild(tile(figures.human.words, "Words by a human"));
  tiles.appendChild(tile(figures.cat.utterances, "cat Utterances"));
  tiles.appendChild(tile(figures.human.utterances, "human Utterances"));
  tiles.appendChild(tile(figures.cat.distinct_words, "different Words by the cat"));
  tiles.appendChild(tile(figures.awaiting_review, "Presses awaiting review"));
  tiles.appendChild(tile(`${figures.observed_hours} h`, "observed"));
  tiles.appendChild(tile(figures.cat.longest.length || "–", "Words in the cat's longest Utterance"));
  panel.appendChild(tiles);

  if (figures.cat.longest.length > 1) {
    const longest = element("p", "hint");
    longest.append("Longest by the cat: ", phraseChips(figures.cat.longest, "cat"));
    panel.appendChild(longest);
  }
  if (!state.day.counted) {
    panel.appendChild(
      element(
        "p",
        "hint",
        `Observed for ${state.day.counted_day_hours} hours or less, so this day is left out of per-day averages.`,
      ),
    );
  }

  panel.appendChild(element("h3", "", `Clips (${state.day.exchanges.length})`));
  const list = element("div", "clip-list");
  if (!state.day.exchanges.length) list.appendChild(element("p", "empty", emptyDayText()));
  for (const exchange of state.day.exchanges) {
    const row = element("button", "clip-row");
    if (exchange.id === state.exchangeId) row.classList.add("selected");
    row.appendChild(element("span", "clip-time", clockTime(exchange.started_at)));
    const chips = element("span", "chips");
    for (const press of exchange.presses) chips.appendChild(wordChip(press.word, press.presser, press.word_uncertain));
    row.appendChild(chips);
    row.addEventListener("click", () => selectExchange(exchange.id, null));
    list.appendChild(row);
  }
  panel.appendChild(list);
  const chosen = list.querySelector(".clip-row.selected");
  if (chosen && state.subtab === "day") chosen.scrollIntoView({ block: "nearest" });
}

function showSubtab(name) {
  state.subtab = name;
  for (const button of document.querySelectorAll(".subtabs button")) {
    button.classList.toggle("active", button.dataset.subtab === name);
  }
  $("subtab-clip").hidden = name !== "clip";
  $("subtab-day").hidden = name !== "day";
}

// ---- Day timeline -------------------------------------------------------------

function themeColour(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function timeToX(seconds, width) {
  return ((seconds - state.view.start) / (state.view.end - state.view.start)) * width;
}

function xToTime(x, width) {
  return state.view.start + (x / width) * (state.view.end - state.view.start);
}

function hourStep(span) {
  for (const step of [60, 300, 600, 1800, 3600, 7200, 10800]) {
    if (span / step <= 12) return step;
  }
  return 21600;
}

function drawDay() {
  const bounds = canvas.parentElement.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(bounds.width, 100);
  const height = 112;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.height = `${height}px`;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  if (!state.day) return;

  const day = state.day;
  const axisHeight = 20;
  const plotHeight = height - axisHeight;
  const laneHeight = plotHeight / LANES.length;
  const sinceMidnight = (time) => time - day.start;

  // Not observed: everything up to now that lies outside the Observation Windows.
  const upToNow = Math.min(sinceMidnight(day.now), DAY_SECONDS);
  context.fillStyle = themeColour("--unobserved");
  context.fillRect(timeToX(0, width), 0, timeToX(Math.max(upToNow, 0), width) - timeToX(0, width), plotHeight);
  context.fillStyle = themeColour("--card");
  for (const window of day.observed) {
    const left = timeToX(sinceMidnight(window.start), width);
    context.fillRect(left, 0, Math.max(timeToX(sinceMidnight(window.end), width) - left, 1), plotHeight);
  }

  // Hour lines and their labels.
  const step = hourStep(state.view.end - state.view.start);
  context.strokeStyle = themeColour("--line");
  context.fillStyle = themeColour("--muted");
  context.font = "11px system-ui, sans-serif";
  context.textAlign = "center";
  context.lineWidth = 1;
  // On a narrow screen the lines stand closer than a label is wide, so some go unlabelled.
  let lastLabelX = -Infinity;
  for (let mark = Math.ceil(state.view.start / step) * step; mark <= state.view.end; mark += step) {
    const x = Math.round(timeToX(mark, width)) + 0.5;
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, plotHeight);
    context.stroke();
    const hours = Math.floor(mark / 3600);
    const minutes = Math.floor((mark % 3600) / 60);
    const label = `${String(hours % 24).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
    if (x > 16 && x < width - 16 && x - lastLabelX >= HOUR_LABEL_SPACING) {
      context.fillText(label, x, height - 6);
      lastLabelX = x;
    }
  }
  for (let lane = 1; lane < LANES.length; lane += 1) {
    context.beginPath();
    context.moveTo(0, lane * laneHeight + 0.5);
    context.lineTo(width, lane * laneHeight + 0.5);
    context.stroke();
  }

  // The chosen Clip, then one tick per Press in its Presser's lane.
  const chosen = currentExchange();
  if (chosen) {
    const left = timeToX(sinceMidnight(chosen.started_at), width) - 4;
    const right = timeToX(sinceMidnight(chosen.ended_at), width) + 4;
    context.fillStyle = themeColour("--selected");
    context.fillRect(left, 0, right - left, plotHeight);
  }
  for (const exchange of day.exchanges) {
    for (const press of exchange.presses) {
      if (press.presser === "discarded") continue;
      const x = timeToX(sinceMidnight(press.pressed_at), width);
      if (x < -2 || x > width + 2) continue;
      context.fillStyle = themeColour(`--${press.presser}`);
      context.fillRect(Math.round(x) - 1, LANES.indexOf(press.presser) * laneHeight + 4, 3, laneHeight - 8);
    }
  }
  if (chosen && !video.hidden && chosen.clip_started_at !== null) {
    const x = Math.round(timeToX(sinceMidnight(chosen.clip_started_at + (video.currentTime || 0)), width)) + 0.5;
    context.strokeStyle = themeColour("--text");
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, plotHeight);
    context.stroke();
  }
}

// The Exchange and Press nearest to a point on the timeline, if one is within reach.
function nearestPress(x, width) {
  if (!state.day) return null;
  let best = null;
  for (const exchange of state.day.exchanges) {
    for (const press of exchange.presses) {
      const distance = Math.abs(timeToX(press.pressed_at - state.day.start, width) - x);
      if (distance <= CLICK_REACH_PX && (!best || distance < best.distance)) best = { exchange, press, distance };
    }
  }
  return best;
}

function zoom(factor, aroundSeconds) {
  const span = state.view.end - state.view.start;
  const newSpan = Math.min(Math.max(span * factor, MIN_VIEW_SECONDS), DAY_SECONDS);
  const centre = aroundSeconds === undefined ? state.view.start + span / 2 : aroundSeconds;
  const share = (centre - state.view.start) / span;
  setView(centre - share * newSpan, newSpan);
}

function setView(start, span) {
  const clamped = Math.min(Math.max(start, 0), DAY_SECONDS - span);
  state.view = { start: clamped, end: clamped + span };
  drawDay();
}

// ---- A Clip asked for by an Utterance Alert ------------------------------------

let askedClipSeenAt = 0; // when the last request acted on was made
let askedClipTimer = null;

// Looks, for a short while, for a request to show one Clip, and shows it once.
function watchForAskedClip() {
  const until = Date.now() + OPEN_CLIP_WATCH_MS;
  clearInterval(askedClipTimer);
  const look = async () => {
    if (Date.now() > until) {
      clearInterval(askedClipTimer);
      return;
    }
    let asked;
    try {
      asked = await api("api/open-clip");
    } catch (error) {
      return; // The page works without it; the next look may succeed.
    }
    if (!asked.exchange_id || asked.asked_at <= askedClipSeenAt) return;
    askedClipSeenAt = asked.asked_at;
    clearInterval(askedClipTimer);
    history.replaceState(null, "", `?day=${asked.day}&clip=${asked.exchange_id}`);
    await loadDay(asked.day, false);
    showSubtab("clip");
  };
  askedClipTimer = setInterval(look, OPEN_CLIP_POLL_MS);
  look();
}

function setUpDayTimeline() {
  const holder = $("day-timeline");
  const tooltip = $("day-tooltip");
  let drag = null;

  holder.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const bounds = canvas.getBoundingClientRect();
      zoom(event.deltaY > 0 ? 1.25 : 0.8, xToTime(event.clientX - bounds.left, bounds.width));
    },
    { passive: false },
  );

  holder.addEventListener("pointerdown", (event) => {
    drag = { x: event.clientX, start: state.view.start, moved: false };
    holder.setPointerCapture(event.pointerId);
  });

  holder.addEventListener("pointermove", (event) => {
    const bounds = canvas.getBoundingClientRect();
    if (drag) {
      const shift = event.clientX - drag.x;
      if (Math.abs(shift) > 3) drag.moved = true;
      if (drag.moved) {
        const span = state.view.end - state.view.start;
        setView(drag.start - (shift / bounds.width) * span, span);
        tooltip.hidden = true;
        return;
      }
    }
    const x = event.clientX - bounds.left;
    const found = nearestPress(x, bounds.width);
    holder.style.cursor = found ? "pointer" : "grab";
    const time = clockTime(state.day ? state.day.start + xToTime(x, bounds.width) : 0);
    tooltip.textContent = found
      ? `${clockTime(found.exchange.started_at)} · ${found.exchange.presses.map((press) => press.word).join(" ")}`
      : time;
    tooltip.hidden = !state.day;
    tooltip.style.left = `${Math.min(Math.max(x, 60), bounds.width - 60)}px`;
  });

  holder.addEventListener("pointerup", (event) => {
    const wasDrag = drag && drag.moved;
    drag = null;
    if (wasDrag) return;
    const bounds = canvas.getBoundingClientRect();
    const found = nearestPress(event.clientX - bounds.left, bounds.width);
    if (!found) return;
    showSubtab("clip");
    selectExchange(found.exchange.id, found.press.id);
  });

  holder.addEventListener("pointerleave", () => {
    tooltip.hidden = true;
  });

  // A finger that turns out to be scrolling the page is taken away from the timeline.
  holder.addEventListener("pointercancel", () => {
    drag = null;
    tooltip.hidden = true;
  });

  $("zoom-in").addEventListener("click", () => zoom(0.5));
  $("zoom-out").addEventListener("click", () => zoom(2));
  $("zoom-reset").addEventListener("click", () => setView(0, DAY_SECONDS));
  window.addEventListener("resize", () => {
    drawDay();
    renderClip(false);
  });
}

// ---- Wiring -------------------------------------------------------------------

function setUpKeys() {
  document.addEventListener("keydown", (event) => {
    if (isTyping(event) || event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    const press = currentPress();
    if (DECISION_KEYS[key] && press) {
      decide(press, DECISION_KEYS[key]);
      stepPress(1);
    } else if (key === "u" && press && press.review_decision) {
      decide(press, null);
    } else if (key === "arrowright") {
      stepPress(1);
    } else if (key === "arrowleft") {
      stepPress(-1);
    } else if (key === "]") {
      stepClip(1);
    } else if (key === "[") {
      stepClip(-1);
    } else if (key === " " && !video.hidden) {
      if (video.paused) video.play();
      else video.pause();
    } else {
      return;
    }
    event.preventDefault();
  });
}

function start() {
  setUpHeader();
  setUpDayTimeline();
  setUpKeys();

  for (const button of document.querySelectorAll(".subtabs button")) {
    button.addEventListener("click", () => showSubtab(button.dataset.subtab));
  }
  $("day-previous").addEventListener("click", () => goToDay(shiftDay(state.day.date, -1)));
  $("day-next").addEventListener("click", () => goToDay(shiftDay(state.day.date, 1)));
  $("day-today").addEventListener("click", () => goToDay(state.day.today));
  $("day-picker").addEventListener("change", (event) => {
    if (event.target.value) goToDay(event.target.value);
  });

  video.addEventListener("loadedmetadata", () => {
    if (state.pendingSeek !== null) video.currentTime = state.pendingSeek;
    state.pendingSeek = null;
  });
  video.addEventListener("timeupdate", () => {
    state.movePlayhead(video.currentTime);
    drawDay();
  });
  video.addEventListener("error", () => {
    if (!video.getAttribute("src")) return;
    video.hidden = true;
    $("player-message").hidden = false;
    $("player-message").textContent = "This Clip could not be played.";
  });

  loadDay(new URLSearchParams(location.search).get("day") || "today", false);
  watchForAskedClip();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") watchForAskedClip();
  });
  // Today keeps filling in; a past day does not change unless a decision is made here.
  setInterval(() => {
    if (state.day && state.day.date === state.day.today && document.visibilityState === "visible") {
      loadDay(state.day.date, true);
    }
  }, DAY_REFRESH_MS);
}

start();
