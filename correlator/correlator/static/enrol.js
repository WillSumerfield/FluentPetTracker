"use strict";

// Enrolment: record the mic feed while every button is pressed, mark each button's sound as a
// Span, and save the Spans as Reference Clips. Word Detection does the work; this page asks.

const RECORDING_POLL_MS = 500;
const IDLE_POLL_MS = 3000;
const SHORTEST_SPAN_SECONDS = 0.2;
const LONGEST_SPAN_SECONDS = 10;
const EDGE_GRAB_PIXELS = 12;
const DRAG_START_PIXELS = 4;
const LARGEST_GAIN = 50;
const STATUS_LAG_MS = 1000; // the Correlator hears of a recording a moment after it starts
const SURE_MS = 4000; // how long "Really remove?" stands before going back
const WORD_PATTERN = /^[a-z0-9][a-z0-9 _-]*$/;
const SPANS_KEY = "fluentpet.enrol.spans";

const state = {
  phase: null, // "idle", "recording" or "ready", as Word Detection last said
  seconds: 0,
  audio: null, // the Enrolment Recording, decoded
  gain: 1, // how far the picture of the sound is stretched, so a quiet recording can be read
  loadedSeconds: null, // which recording the audio and Spans belong to
  spans: [], // { id, start, end, word }
  selected: null, // a Span's id
  view: null, // the stretch the close-up shows: { start, end }
  words: [],
  busy: false,
  nextId: 1,
};

let audioContext = null;
let playing = null; // { source, from, startedAt, until, timer }
let pollTimer = null;

// ---- Talking to Word Detection ------------------------------------------------

function enrolment(path, options) {
  return api(`api/enrolment/${path}`, options);
}

function send(path, body) {
  const options = { method: "POST" };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  return enrolment(path, options);
}

async function poll() {
  clearTimeout(pollTimer);
  try {
    showState(await enrolment("state"));
    clearProblem();
  } catch (error) {
    showProblem(error);
  }
  pollTimer = setTimeout(poll, state.phase === "recording" ? RECORDING_POLL_MS : IDLE_POLL_MS);
}

// Does one thing that changes the Enrolment, with the buttons held until it is done.
async function act(work) {
  if (state.busy) return;
  state.busy = true;
  try {
    await work();
    clearProblem();
  } catch (error) {
    showProblem(error);
  } finally {
    state.busy = false;
  }
}

// ---- The three phases ---------------------------------------------------------

function showState(now) {
  const changed = now.state !== state.phase;
  state.phase = now.state;
  state.seconds = now.seconds;
  $("idle").hidden = now.state !== "idle";
  $("recording").hidden = now.state !== "recording";
  $("ready").hidden = now.state !== "ready";

  if (now.state === "idle") {
    $("enrol-state").textContent = "";
    $("start").disabled = !now.hearing;
    $("idle-note").textContent = now.hearing
      ? `A recording stops by itself after ${Math.round(now.limit_seconds / 60)} minutes.`
      : "The mic feed is not being heard, so there is nothing to record. Is the camera on?";
    forgetRecording();
  } else if (now.state === "recording") {
    $("enrol-state").textContent = "Recording";
    $("elapsed").textContent = minutes(now.seconds);
    $("limit").textContent = `of ${minutes(now.limit_seconds)}`;
    // Shown on a curve: a button at arm's length is far from filling the scale.
    $("level").style.width = `${Math.min(Math.sqrt(now.level) * 100, 100)}%`;
    forgetRecording();
  } else {
    $("enrol-state").textContent = "Ready to mark up";
    $("recording-title").textContent = `Enrolment Recording · ${minutes(now.seconds)}`;
    $("recording-note").textContent = now.ended_because ? `It ended because ${now.ended_because}.` : "";
    if (state.loadedSeconds !== now.seconds) loadRecording(now.seconds);
  }
  if (changed) {
    $("saved").hidden = $("saved").hidden || now.state !== "idle";
    // The status line says whether an Enrolment is in progress; it should not lag behind the page.
    setTimeout(refreshStatus, STATUS_LAG_MS);
  }
}

function forgetRecording() {
  if (state.loadedSeconds === null) return;
  stopPlaying();
  state.audio = null;
  state.loadedSeconds = null;
  state.spans = [];
  state.selected = null;
}

async function loadRecording(seconds) {
  state.loadedSeconds = seconds;
  state.audio = null;
  $("loading").hidden = false;
  $("loading").textContent = "Loading the recording…";
  $("marking").hidden = true;
  try {
    const audio = await fetchAudio("api/enrolment/recording.wav");
    if (state.loadedSeconds !== seconds) return; // replaced while it was loading
    state.audio = audio;
    state.gain = drawingGain(audio);
    state.spans = keptSpans(seconds) || (await suggestedSpans());
    state.selected = state.spans.length ? state.spans[0].id : null;
    state.view = null;
    $("loading").hidden = true;
    $("marking").hidden = false;
    $("confirm").hidden = true;
    $("save-bar").hidden = false;
    render();
  } catch (error) {
    state.loadedSeconds = null; // so the next look at the state tries again
    $("loading").textContent = "The recording could not be loaded. Trying again…";
    showProblem(error);
  }
}

async function suggestedSpans() {
  const suggested = (await enrolment("spans")).spans;
  return suggested.map((span) => ({ id: state.nextId++, start: span.start, end: span.end, word: "" }));
}

// ---- Keeping the mark-up across a reload --------------------------------------

function keepSpans() {
  try {
    const kept = { seconds: state.loadedSeconds, spans: state.spans.map(({ start, end, word }) => ({ start, end, word })) };
    localStorage.setItem(SPANS_KEY, JSON.stringify(kept));
  } catch (error) {
    // The mark-up then lasts only until the page is closed.
  }
}

function keptSpans(seconds) {
  try {
    const kept = JSON.parse(localStorage.getItem(SPANS_KEY));
    if (!kept || kept.seconds !== seconds || !Array.isArray(kept.spans)) return null;
    return kept.spans.map((span) => ({ id: state.nextId++, start: span.start, end: span.end, word: span.word || "" }));
  } catch (error) {
    return null;
  }
}

// ---- Sound --------------------------------------------------------------------

async function fetchAudio(address) {
  let reply;
  try {
    reply = await fetch(address, { cache: "no-store" });
  } catch (error) {
    throw new Error("The Correlator's web service cannot be reached.");
  }
  if (!reply.ok) throw new Error(`The sound could not be fetched (${reply.status}).`);
  if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
  try {
    return await audioContext.decodeAudioData(await reply.arrayBuffer());
  } catch (error) {
    throw new Error("The sound could not be read by this browser.");
  }
}

function stopPlaying() {
  if (!playing) return;
  clearTimeout(playing.timer);
  playing.source.onended = null;
  try {
    playing.source.stop();
  } catch (error) {
    // It had already finished.
  }
  if (playing.done) playing.done();
  playing = null;
  drawWaves();
}

// Plays part of a decoded sound. `from` and `until` are seconds into it.
async function play(audio, from, until, done) {
  stopPlaying();
  if (!audio) return;
  try {
    if (audioContext.state === "suspended") await audioContext.resume();
  } catch (error) {
    showProblem(new Error("This browser would not play the sound. Click the page and try again."));
    return;
  }
  const source = audioContext.createBufferSource();
  source.buffer = audio;
  source.connect(audioContext.destination);
  const length = Math.max(Math.min(until, audio.duration) - from, 0.05);
  source.start(0, from, length);
  playing = { source, from, until: from + length, startedAt: audioContext.currentTime, done, isRecording: audio === state.audio };
  source.onended = stopPlaying;
  if (playing.isRecording) requestAnimationFrame(followPlayhead);
}

function playhead() {
  if (!playing || !playing.isRecording) return null;
  return Math.min(playing.from + audioContext.currentTime - playing.startedAt, playing.until);
}

function followPlayhead() {
  if (!playing || !playing.isRecording) return;
  drawWaves();
  requestAnimationFrame(followPlayhead);
}

// ---- Spans --------------------------------------------------------------------

function selectedSpan() {
  return state.spans.find((span) => span.id === state.selected) || null;
}

function select(id, focusWord) {
  if (state.selected !== id) {
    state.selected = id;
    state.view = null;
    stopPlaying();
  }
  render();
  if (focusWord) {
    const input = document.querySelector(`.span-row[data-id="${id}"] input`);
    if (input) input.focus();
  }
}

function step(by, focusWord) {
  if (!state.spans.length) return;
  const at = state.spans.findIndex((span) => span.id === state.selected);
  const next = state.spans[Math.min(Math.max(at + by, 0), state.spans.length - 1)];
  select(next.id, focusWord);
  const row = document.querySelector(`.span-row[data-id="${next.id}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
}

function playSelected() {
  const span = selectedSpan();
  if (span) play(state.audio, span.start, span.end);
}

function addSpan(start, end) {
  const span = { id: state.nextId++, start, end, word: "" };
  state.spans.push(span);
  state.spans.sort((first, second) => first.start - second.start);
  state.selected = span.id;
  state.view = null;
  keepSpans();
  render();
  const input = document.querySelector(`.span-row[data-id="${span.id}"] input`);
  if (input) input.focus();
}

function deleteSpan(id) {
  const at = state.spans.findIndex((span) => span.id === id);
  if (at === -1) return;
  stopPlaying();
  state.spans.splice(at, 1);
  if (state.selected === id) {
    const next = state.spans[Math.min(at, state.spans.length - 1)];
    state.selected = next ? next.id : null;
    state.view = null;
  }
  keepSpans();
  render();
}

function cleanWord(text) {
  return text.trim().toLowerCase().replace(/\s+/g, " ");
}

// ---- Drawing ------------------------------------------------------------------

function render() {
  renderSpanList();
  renderDetailHead();
  renderSaveBar();
  drawWaves();
}

function renderSpanList() {
  const list = $("spans");
  // Typing must not be interrupted, so the list is only rebuilt when its Spans have changed.
  const shape = state.spans.map((span) => `${span.id}:${span.start}:${span.end}`).join("|");
  if (list.dataset.shape !== shape) {
    list.dataset.shape = shape;
    list.replaceChildren(...state.spans.map(spanRow));
  }
  for (const row of list.children) row.classList.toggle("selected", Number(row.dataset.id) === state.selected);
  $("no-spans").hidden = state.spans.length > 0;
}

function spanRow(span, index) {
  const row = element("div", "span-row");
  row.dataset.id = span.id;
  row.appendChild(element("span", "span-number", index + 1));
  row.appendChild(element("span", "span-when", `${minutes(span.start, true)} · ${(span.end - span.start).toFixed(2)} s`));

  const input = element("input");
  input.type = "text";
  input.placeholder = "Word";
  input.value = span.word;
  input.autocapitalize = "none";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("list", "known-words");
  input.setAttribute("aria-label", `Word of Span ${index + 1}`);
  input.classList.toggle("bad", Boolean(span.word) && !WORD_PATTERN.test(span.word));
  input.addEventListener("focus", () => select(span.id, false));
  input.addEventListener("input", () => {
    span.word = cleanWord(input.value);
    input.classList.toggle("bad", Boolean(span.word) && !WORD_PATTERN.test(span.word));
    keepSpans();
    renderSaveBar();
    drawWaves();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    step(1, true);
    playSelected();
  });
  row.appendChild(input);

  const listen = element("button", "quiet", "Play");
  listen.addEventListener("click", () => {
    select(span.id, false);
    playSelected();
  });
  const remove = element("button", "quiet danger", "Delete");
  remove.addEventListener("click", () => deleteSpan(span.id));
  row.append(listen, remove);
  row.addEventListener("click", (event) => {
    if (event.target === row || event.target.tagName === "SPAN") select(span.id, false);
  });
  return row;
}

function renderDetailHead() {
  const span = selectedSpan();
  $("detail").hidden = !span;
  if (!span) return;
  const number = state.spans.indexOf(span) + 1;
  $("detail-title").textContent = `Span ${number}${span.word ? ` · ${span.word}` : ""} · ${(span.end - span.start).toFixed(2)} s`;
}

// What saving would do: the Words, how many Reference Clips each gets, and what stands in the way.
function savePlan() {
  const counts = new Map();
  let unlabelled = 0;
  let bad = 0;
  for (const span of state.spans) {
    if (!span.word) unlabelled += 1;
    else if (!WORD_PATTERN.test(span.word)) bad += 1;
    else counts.set(span.word, (counts.get(span.word) || 0) + 1);
  }
  return { counts, unlabelled, bad, clips: [...counts.values()].reduce((total, count) => total + count, 0) };
}

function renderSaveBar() {
  const plan = savePlan();
  const notes = [];
  if (plan.bad) notes.push(`${plural(plan.bad, "Word")} cannot be used: lower-case letters, digits, spaces, - or _ only.`);
  if (plan.unlabelled) notes.push(`${plural(plan.unlabelled, "Span")} without a Word will be left out.`);
  $("save-note").textContent = notes.join(" ");
  $("save").disabled = plan.bad > 0 || plan.clips === 0;
  $("save").textContent = plan.clips
    ? `Save ${plural(plan.clips, "Reference Clip")} for ${plural(plan.counts.size, "Word")}`
    : "Save Reference Clips";
}

function colour(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Sizes a canvas for sharp drawing and returns what is needed to draw on it.
function prepare(canvas) {
  const scale = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * scale) || canvas.height !== Math.round(height * scale)) {
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
  }
  const context = canvas.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.clearRect(0, 0, width, height);
  return { context, width, height };
}

// A button heard from across the room fills little of the scale, so the picture is stretched
// until the loudest moment nearly fills it.
function drawingGain(audio) {
  const samples = audio.getChannelData(0);
  let loudest = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const size = Math.abs(samples[index]);
    if (size > loudest) loudest = size;
  }
  return Math.min(1 / Math.max(loudest, 0.01), LARGEST_GAIN);
}

// Draws the sound between two moments as one upright stroke per pixel.
function drawSound(context, width, height, start, end, paint) {
  const samples = state.audio.getChannelData(0);
  const rate = state.audio.sampleRate;
  const middle = height / 2;
  const reach = middle * 0.95 * state.gain;
  context.fillStyle = paint;
  for (let x = 0; x < width; x += 1) {
    const from = Math.max(Math.floor((start + ((end - start) * x) / width) * rate), 0);
    const to = Math.min(Math.floor((start + ((end - start) * (x + 1)) / width) * rate), samples.length);
    let low = 0;
    let high = 0;
    // A long recording has thousands of samples to the pixel; a sparse look at them is enough.
    const stride = Math.max(Math.floor((to - from) / 200), 1);
    for (let index = from; index < to; index += stride) {
      if (samples[index] < low) low = samples[index];
      if (samples[index] > high) high = samples[index];
    }
    const top = middle - high * reach;
    context.fillRect(x, top, 1, Math.max(middle - low * reach - top, 1));
  }
}

function drawWaves() {
  if (!state.audio || $("marking").hidden) return;
  drawOverview();
  drawCloseUp();
}

function drawOverview() {
  const { context, width, height } = prepare($("overview"));
  const length = state.audio.duration;
  const place = (seconds) => (seconds / length) * width;

  for (const span of drag && drag.adding ? [...state.spans, drag.adding] : state.spans) {
    const chosen = span.id === state.selected;
    context.fillStyle = colour(span.word ? "--pet-soft" : "--ambiguous-soft");
    context.fillRect(place(span.start), 0, Math.max(place(span.end) - place(span.start), 2), height);
    if (chosen) {
      context.strokeStyle = colour("--text");
      context.lineWidth = 2;
      context.strokeRect(place(span.start) + 1, 1, Math.max(place(span.end) - place(span.start) - 2, 2), height - 2);
    }
  }
  drawSound(context, width, height, 0, length, colour("--muted"));

  context.font = "600 11px system-ui, sans-serif";
  context.textBaseline = "top";
  state.spans.forEach((span, index) => {
    context.fillStyle = colour(span.word ? "--pet" : "--ambiguous");
    context.fillText(span.word || String(index + 1), place(span.start) + 3, 3);
  });
  drawPlayhead(context, place, height);
}

// The close-up keeps to one stretch while an edge is dragged, so the sound does not slide
// about under the pointer.
function closeUpView() {
  const span = selectedSpan();
  if (!span) return null;
  if (!state.view) {
    const margin = Math.max((span.end - span.start) * 0.35, 0.5);
    state.view = { start: Math.max(span.start - margin, 0), end: Math.min(span.end + margin, state.audio.duration) };
  }
  return state.view;
}

function drawCloseUp() {
  const span = selectedSpan();
  const view = closeUpView();
  if (!span || !view) return;
  const { context, width, height } = prepare($("close-up"));
  const place = (seconds) => ((seconds - view.start) / (view.end - view.start)) * width;

  context.fillStyle = colour(span.word ? "--pet-soft" : "--ambiguous-soft");
  context.fillRect(place(span.start), 0, place(span.end) - place(span.start), height);
  drawSound(context, width, height, view.start, view.end, colour("--muted"));

  // The two edges, with a grip at the middle of each.
  context.fillStyle = colour(span.word ? "--pet" : "--ambiguous");
  for (const edge of [span.start, span.end]) {
    context.fillRect(place(edge) - 1, 0, 2, height);
    context.fillRect(place(edge) - 4, height / 2 - 14, 8, 28);
  }
  context.font = "11px system-ui, sans-serif";
  context.textBaseline = "bottom";
  context.fillStyle = colour("--muted");
  context.textAlign = "left";
  context.fillText(minutes(view.start, true), 4, height - 3);
  context.textAlign = "right";
  context.fillText(minutes(view.end, true), width - 4, height - 3);
  context.textAlign = "left";
  drawPlayhead(context, place, height);
}

function drawPlayhead(context, place, height) {
  const at = playhead();
  if (at === null) return;
  context.fillStyle = colour("--danger");
  context.fillRect(place(at) - 1, 0, 2, height);
}

// ---- Dragging on the two pictures ---------------------------------------------

let drag = null;

function secondsAt(canvas, event, start, end) {
  const bounds = canvas.getBoundingClientRect();
  const share = Math.min(Math.max((event.clientX - bounds.left) / bounds.width, 0), 1);
  return start + share * (end - start);
}

function setUpOverview() {
  const canvas = $("overview");
  canvas.addEventListener("pointerdown", (event) => {
    if (!state.audio) return;
    const at = secondsAt(canvas, event, 0, state.audio.duration);
    const hit = state.spans.find((span) => at >= span.start && at <= span.end);
    drag = { on: canvas, from: at, x: event.clientX, hit, adding: null };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag || drag.on !== canvas) return;
    if (!drag.adding && Math.abs(event.clientX - drag.x) < DRAG_START_PIXELS) return;
    const at = secondsAt(canvas, event, 0, state.audio.duration);
    drag.adding = { id: -1, start: Math.min(drag.from, at), end: Math.max(drag.from, at), word: "" };
    drawWaves();
  });
  const finish = () => {
    if (!drag || drag.on !== canvas) return;
    const { adding, hit } = drag;
    drag = null;
    if (adding) {
      const end = Math.min(adding.end, adding.start + LONGEST_SPAN_SECONDS);
      if (end - adding.start >= SHORTEST_SPAN_SECONDS) addSpan(adding.start, end);
      else drawWaves();
    } else if (hit) {
      select(hit.id, false);
      playSelected();
    }
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

function setUpCloseUp() {
  const canvas = $("close-up");
  const edgeNear = (event) => {
    const span = selectedSpan();
    const view = state.view;
    if (!span || !view) return null;
    const bounds = canvas.getBoundingClientRect();
    const pixel = (seconds) => bounds.left + ((seconds - view.start) / (view.end - view.start)) * bounds.width;
    const toStart = Math.abs(event.clientX - pixel(span.start));
    const toEnd = Math.abs(event.clientX - pixel(span.end));
    if (Math.min(toStart, toEnd) > EDGE_GRAB_PIXELS) return null;
    return toStart <= toEnd ? "start" : "end";
  };
  canvas.addEventListener("pointerdown", (event) => {
    const span = selectedSpan();
    if (!span) return;
    drag = { on: canvas, edge: edgeNear(event) };
    canvas.setPointerCapture(event.pointerId);
    if (drag.edge) stopPlaying();
  });
  canvas.addEventListener("pointermove", (event) => {
    const span = selectedSpan();
    if (!span) return;
    if (!drag || drag.on !== canvas) {
      canvas.style.cursor = edgeNear(event) ? "ew-resize" : "pointer";
      return;
    }
    if (!drag.edge) return;
    const at = secondsAt(canvas, event, state.view.start, state.view.end);
    if (drag.edge === "start") {
      span.start = Math.min(Math.max(at, span.end - LONGEST_SPAN_SECONDS), span.end - SHORTEST_SPAN_SECONDS);
    } else {
      span.end = Math.max(Math.min(at, span.start + LONGEST_SPAN_SECONDS), span.start + SHORTEST_SPAN_SECONDS);
    }
    span.start = Math.max(span.start, 0);
    span.end = Math.min(span.end, state.audio.duration);
    drag.moved = true;
    renderDetailHead();
    drawWaves();
  });
  const finish = (event) => {
    if (!drag || drag.on !== canvas) return;
    const { edge, moved } = drag;
    drag = null;
    const span = selectedSpan();
    if (!span) return;
    if (edge && moved) {
      // The new edge is heard at once: the start from its beginning, the end by its last moments.
      state.spans.sort((first, second) => first.start - second.start);
      state.view = null;
      keepSpans();
      render();
      play(state.audio, edge === "start" ? span.start : Math.max(span.end - 0.6, span.start), span.end);
    } else if (!edge) {
      const at = secondsAt(canvas, event, state.view.start, state.view.end);
      play(state.audio, at, at < span.end && at >= span.start ? span.end : state.view.end);
    }
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

// ---- Saving -------------------------------------------------------------------

function askToSave() {
  const plan = savePlan();
  if (plan.bad || !plan.clips) return;
  const enrolled = new Map(state.words.map((word) => [word.word, word.clips.length]));
  const lines = [];
  let replacing = 0;
  for (const [word, count] of [...plan.counts].sort()) {
    const had = enrolled.get(word) || 0;
    replacing += had;
    const line = element("li");
    line.append(wordChip(word, "pet", false), ` ${plural(count, "Reference Clip")}`);
    line.append(had ? `, replacing the ${had === 1 ? "one" : had} it has now` : ", a new Word");
    lines.push(line);
  }
  $("confirm-list").replaceChildren(...lines);
  const notes = ["Words not listed keep the Reference Clips they have. The recording is discarded once saved."];
  if (plan.unlabelled) notes.unshift(`${plural(plan.unlabelled, "Span")} without a Word will be left out.`);
  $("confirm-note").textContent = notes.join(" ");
  $("confirm-save").textContent = replacing ? "Save and replace" : "Save";
  $("confirm").hidden = false;
  $("save-bar").hidden = true;
  $("confirm").scrollIntoView({ block: "nearest" });
}

function backFromSaving() {
  $("confirm").hidden = true;
  $("save-bar").hidden = false;
}

function save() {
  return act(async () => {
    const spans = state.spans
      .filter((span) => span.word)
      .map(({ start, end, word }) => ({ start, end, word }));
    const result = await send("save", { spans });
    const total = result.saved.reduce((sum, word) => sum + word.clips, 0);
    $("saved").textContent = `Saved ${plural(total, "Reference Clip")} for ${plural(result.saved.length, "Word")}: ${result.saved.map((word) => word.word).join(", ")}. Word Detection is using them now.`;
    try {
      localStorage.removeItem(SPANS_KEY);
    } catch (error) {
      // Nothing was kept, then.
    }
    await Promise.all([poll(), loadWords()]);
    $("saved").hidden = false;
  });
}

// ---- Enrolled Words -----------------------------------------------------------

async function loadWords() {
  try {
    state.words = (await enrolment("words")).words;
  } catch (error) {
    $("words").replaceChildren(element("p", "empty small", "The enrolled Words could not be read."));
    return;
  }
  renderWords();
}

function renderWords() {
  $("known-words").replaceChildren(
    ...state.words.map((word) => {
      const option = element("option");
      option.value = word.word;
      return option;
    }),
  );
  if (!state.words.length) {
    $("words").replaceChildren(
      element("p", "empty small", "No Word is enrolled yet, so Word Detection reports nothing. Record the board to begin."),
    );
    return;
  }
  $("words").replaceChildren(...state.words.map(wordRow));
  if (!$("confirm").hidden) askToSave(); // what would be replaced may have changed
}

function wordRow(word) {
  const row = element("div", "word-row");
  row.appendChild(wordChip(word.word, "pet", false));
  const clips = element("div", "word-clips");
  for (const clip of word.clips) {
    const pill = element("span", "clip-pill");
    const number = clip.name.replace(".wav", "");
    const listen = element("button", "", `▶ ${number}${clip.seconds === null ? " · unreadable" : ` · ${clip.seconds.toFixed(2)} s`}`);
    listen.title = `Play Reference Clip ${number} of "${word.word}"`;
    listen.disabled = clip.seconds === null;
    listen.addEventListener("click", () => playClip(word.word, clip.name, pill));
    const remove = element("button", "", "✕");
    remove.title = `Remove Reference Clip ${number} of "${word.word}"`;
    remove.setAttribute("aria-label", remove.title);
    whenSure(remove, "Remove?", () => removeEnrolled(`${encodeURIComponent(word.word)}/${clip.name}`));
    pill.append(listen, remove);
    clips.appendChild(pill);
  }
  row.appendChild(clips);
  const removeWord = element("button", "quiet", "Remove Word");
  whenSure(removeWord, "Really remove?", () => removeEnrolled(encodeURIComponent(word.word)));
  row.appendChild(removeWord);
  return row;
}

// Removing cannot be undone, so a button asks once more in its own place before it acts.
function whenSure(button, question, action) {
  const label = button.textContent;
  let timer = null;
  button.addEventListener("click", () => {
    if (button.classList.contains("sure")) {
      clearTimeout(timer);
      action();
      return;
    }
    button.classList.add("sure");
    button.textContent = question;
    timer = setTimeout(() => {
      button.classList.remove("sure");
      button.textContent = label;
    }, SURE_MS);
  });
}

async function playClip(word, name, pill) {
  try {
    const audio = await fetchAudio(`api/enrolment/words/${encodeURIComponent(word)}/${name}`);
    await play(audio, 0, audio.duration, () => pill.classList.remove("playing"));
    pill.classList.add("playing");
    clearProblem();
  } catch (error) {
    showProblem(error);
  }
}

function removeEnrolled(path) {
  return act(async () => {
    stopPlaying();
    state.words = (await enrolment(`words/${path}`, { method: "DELETE" })).words;
    renderWords();
  });
}

// ---- Wording ------------------------------------------------------------------

function minutes(seconds, exact) {
  const whole = Math.floor(seconds / 60);
  const rest = seconds - whole * 60;
  if (exact) return `${whole}:${rest.toFixed(1).padStart(4, "0")}`;
  return `${whole}:${String(Math.floor(rest)).padStart(2, "0")}`;
}

// ---- Wiring -------------------------------------------------------------------

function start() {
  setUpHeader();

  $("start").addEventListener("click", () => act(async () => showState(await send("start"))));
  $("stop").addEventListener("click", () => act(async () => showState(await send("stop"))));
  whenSure($("discard"), "Really discard?", () => act(async () => showState(await send("discard"))));
  whenSure($("again"), "Discard and record again?", () => act(async () => showState(await send("start"))));
  $("play").addEventListener("click", playSelected);
  $("delete").addEventListener("click", () => deleteSpan(state.selected));
  $("save").addEventListener("click", askToSave);
  $("confirm-back").addEventListener("click", backFromSaving);
  $("confirm-save").addEventListener("click", save);
  setUpOverview();
  setUpCloseUp();

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || !state.audio || $("marking").hidden) return;
    const typing = isTyping(event);
    if (event.key === "ArrowDown") step(1, typing);
    else if (event.key === "ArrowUp") step(-1, typing);
    else if (typing) return;
    else if (event.key === " ") {
      if (playing) stopPlaying();
      else playSelected();
    } else if (event.key === "Delete" || event.key === "Backspace") deleteSpan(state.selected);
    else return;
    event.preventDefault();
  });

  window.addEventListener("resize", drawWaves);
  onWake(() => {
    poll();
    loadWords();
  });
  loadWords();
  poll();
}

start();
