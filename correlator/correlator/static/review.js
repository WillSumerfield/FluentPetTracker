"use strict";

// Review: the Review Queue one Press at a time, oldest first. A key decides and moves on.

const LOOP_BEFORE_SECONDS = 3;
const LOOP_AFTER_SECONDS = 3;
// Under the left hand, so a sitting can be worked through without looking down.
const REVIEW_KEYS = { a: "cat", d: "human", s: "discarded" };

const state = {
  exchange: null,
  press: null,
  skippedPast: 0, // Presses up to this one have been skipped in this sitting
  decided: [], // { pressId, exchangeId } in the order decided, for undo
  busy: false,
  movePlayhead: () => {},
};

const video = $("video");

// ---- Showing a Press ----------------------------------------------------------

async function showNext() {
  try {
    const next = await api(`api/review/next?after=${state.skippedPast}`);
    clearProblem();
    $("remaining").textContent = `${plural(next.remaining, "Press", "Presses")} awaiting review`;
    if (next.exchange === null) {
      showNothingLeft(next.remaining);
      return;
    }
    show(next.exchange, next.press_id);
  } catch (error) {
    showProblem(error);
  }
}

function showNothingLeft(remaining) {
  state.exchange = null;
  state.press = null;
  video.pause();
  video.hidden = true;
  $("strip").hidden = true;
  $("panel").hidden = true;
  $("player-message").hidden = false;
  $("player-message").textContent = remaining
    ? `You have skipped the ${plural(remaining, "Press", "Presses")} still awaiting review. Reload the page to see them again.`
    : "Nothing is awaiting review. Every Ambiguous Press has a Review Decision.";
}

function show(exchange, pressId) {
  const newClip = !state.exchange || state.exchange.id !== exchange.id;
  state.exchange = exchange;
  state.press = exchange.presses.find((press) => press.id === pressId);

  $("panel").hidden = false;
  $("strip").hidden = false;
  $("press-word").replaceChildren(wordChip(state.press.word, state.press.presser, state.press.word_uncertain));
  $("press-when").textContent = `${dayName(isoDate(new Date(state.press.pressed_at * 1000)))}, ${clockTime(state.press.pressed_at)}`;
  $("press-reason").textContent = AMBIGUITY_REASONS[state.press.ambiguity] || "";
  $("clip-title").textContent = `Clip at ${clockTime(exchange.started_at)}`;
  $("open-daily").href = `./?day=${isoDate(new Date(exchange.started_at * 1000))}&clip=${exchange.id}&press=${pressId}`;
  $("undo").disabled = state.decided.length === 0;
  $("session").textContent = state.decided.length ? `${plural(state.decided.length, "decision")} made in this sitting.` : "";

  if (exchange.clip_url) {
    $("player-message").hidden = true;
    video.hidden = false;
    if (newClip) {
      video.src = exchange.clip_url;
    } else {
      restartLoop();
    }
  } else {
    video.pause();
    video.removeAttribute("src");
    video.hidden = true;
    $("player-message").hidden = false;
    $("player-message").textContent = `${clipStatusText(exchange)} You can skip this Press and come back to it.`;
  }
  drawTimeline();
}

function drawTimeline() {
  if (!state.exchange) return;
  state.movePlayhead = drawClipTimeline($("clip-timeline"), state.exchange, {
    selectedPressId: state.press.id,
    // Looking elsewhere in the Clip only makes sense with the loop around the Press let go.
    onSeek: (seconds) => {
      $("whole-clip").checked = true;
      video.currentTime = seconds;
    },
    onPress: (press, offset) => {
      $("whole-clip").checked = true;
      video.currentTime = Math.max(offset - 1, 0);
    },
  });
}

// ---- Looping around the Press -------------------------------------------------

function loopSpan() {
  const offset = clipOffset(state.exchange, state.press) || 0;
  if ($("whole-clip").checked) return { start: 0, end: video.duration || offset + LOOP_AFTER_SECONDS };
  return {
    start: Math.max(offset - LOOP_BEFORE_SECONDS, 0),
    end: Math.min(offset + LOOP_AFTER_SECONDS, video.duration || Infinity),
  };
}

function restartLoop() {
  if (video.hidden || !state.press) return;
  video.currentTime = loopSpan().start;
  // Browsers refuse to start a video with sound unasked; it stays paused until a key or click.
  video.play().catch(() => {});
}

// ---- Deciding -----------------------------------------------------------------

async function decide(decision) {
  if (state.busy || !state.press) return;
  state.busy = true;
  try {
    await sendReview("presses", state.press.id, decision);
    state.decided.push({ pressId: state.press.id, exchangeId: state.exchange.id });
    await showNext();
  } catch (error) {
    showProblem(error);
  } finally {
    state.busy = false;
  }
}

async function skip() {
  if (state.busy || !state.press) return;
  state.skippedPast = state.press.id;
  await showNext();
}

async function undo() {
  if (state.busy || !state.decided.length) return;
  state.busy = true;
  const last = state.decided.pop();
  try {
    const exchange = await sendReview("presses", last.pressId, null);
    // The withdrawn Press is the oldest one awaiting review again, unless it was skipped past.
    state.skippedPast = Math.min(state.skippedPast, last.pressId - 1);
    show(exchange, last.pressId);
    refreshStatus();
    const next = await api(`api/review/next?after=${state.skippedPast}`);
    $("remaining").textContent = `${plural(next.remaining, "Press", "Presses")} awaiting review`;
  } catch (error) {
    state.decided.push(last);
    showProblem(error);
  } finally {
    state.busy = false;
  }
}

// ---- Wiring -------------------------------------------------------------------

function start() {
  setUpHeader();

  for (const button of document.querySelectorAll("[data-decision]")) {
    button.addEventListener("click", () => decide(button.dataset.decision));
  }
  $("skip").addEventListener("click", skip);
  $("undo").addEventListener("click", undo);
  $("whole-clip").addEventListener("change", restartLoop);
  $("sound").addEventListener("change", (event) => {
    video.muted = !event.target.checked;
  });

  video.addEventListener("loadedmetadata", restartLoop);
  video.addEventListener("timeupdate", () => {
    state.movePlayhead(video.currentTime);
    const span = loopSpan();
    if (video.currentTime >= span.end || video.currentTime < span.start - 0.5) video.currentTime = span.start;
  });
  video.addEventListener("ended", restartLoop);
  video.addEventListener("click", () => {
    if (video.paused) video.play();
    else video.pause();
  });
  video.addEventListener("error", () => {
    if (!video.getAttribute("src")) return;
    video.hidden = true;
    $("player-message").hidden = false;
    $("player-message").textContent = "This Clip could not be played. You can still decide, or skip it.";
  });

  document.addEventListener("keydown", (event) => {
    if (isTyping(event) && event.target.type !== "checkbox") return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    if (REVIEW_KEYS[key]) decide(REVIEW_KEYS[key]);
    else if (key === "w") skip();
    else if (key === "z") undo();
    else if (key === "e") $("whole-clip").click();
    else if (key === "m") $("sound").click();
    else if (key === " " && !video.hidden) {
      if (video.paused) video.play();
      else video.pause();
    } else return;
    event.preventDefault();
  });

  window.addEventListener("resize", drawTimeline);
  showNext();
}

start();
