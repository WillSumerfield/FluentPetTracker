"use strict";

// Shared by every page: talking to the Correlator, wording, and the pieces more than one page draws.

const STATUS_REFRESH_MS = 10000;

const PAGES = [
  { path: "./", title: "Daily Summary" },
  { path: "review", title: "Review" },
  { path: "live", title: "Live Feed" },
  { path: "metrics", title: "Metrics" },
];

const PRESSER_LABELS = { cat: "Cat", human: "Human", ambiguous: "Ambiguous", discarded: "Discarded" };
const DECISION_LABELS = { cat: "Cat", human: "Human", discarded: "Discard" };
const DECISION_KEYS = { c: "cat", h: "human", d: "discarded" };
const AMBIGUITY_REASONS = {
  both: "The cat and a person were both at the Board.",
  nobody: "Nobody was seen at the Board.",
};

const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

async function api(path, options) {
  let reply;
  try {
    reply = await fetch(path, options);
  } catch (error) {
    throw new Error("The Correlator's web service cannot be reached.");
  }
  let body = null;
  try {
    body = await reply.json();
  } catch (error) {
    // Handled below: a reply without JSON is a failure unless the status says otherwise.
  }
  if (!reply.ok || body === null) {
    throw new Error((body && body.error) || `The request failed (${reply.status}).`);
  }
  return body;
}

function sendReview(kind, id, decision) {
  return api(`api/${kind}/${id}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
}

function showProblem(error) {
  $("notice").textContent = error.message;
  $("notice").hidden = false;
}

function clearProblem() {
  $("notice").hidden = true;
}

// ---- Wording ------------------------------------------------------------------

function clockTime(seconds, withSeconds = true) {
  const options = { hour: "2-digit", minute: "2-digit" };
  if (withSeconds) options.second = "2-digit";
  return new Date(seconds * 1000).toLocaleTimeString([], options);
}

function dayName(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString([], {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function isoDate(when) {
  const pad = (number) => String(number).padStart(2, "0");
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

function shiftDay(isoDay, days) {
  const [year, month, day] = isoDay.split("-").map(Number);
  return isoDate(new Date(year, month - 1, day + days));
}

function duration(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  if (seconds < 60) return `${Math.round(seconds * 10) / 10} s`;
  if (seconds < 3600) return `${Math.round(seconds / 6) / 10} min`;
  return `${Math.round(seconds / 360) / 10} h`;
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many || `${one}s`}`;
}

function isTyping(event) {
  return ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName);
}

// ---- Shared pieces ------------------------------------------------------------

function wordChip(word, presser, uncertain) {
  const chip = element("span", `chip ${presser}`, word);
  if (uncertain) {
    chip.classList.add("uncertain");
    chip.title = "Uncertain Match: Word Detection was not sure of this Word.";
  }
  return chip;
}

function phraseChips(words, presser) {
  const row = element("span", "chips");
  for (const word of words) row.appendChild(wordChip(word, presser, false));
  return row;
}

// A sidebar listing the pages is only needed outside Home Assistant, whose own sidebar lists them.
function setUpHeader() {
  if (window.self === window.top) addSidebar();
  // Inside Home Assistant the keyboard belongs to its own page until this one asks for it.
  else window.focus();
  refreshStatus();
  setInterval(refreshStatus, STATUS_REFRESH_MS);
}

function addSidebar() {
  const sidebar = element("aside", "sidebar");
  sidebar.appendChild(element("p", "sidebar-title", "FluentPet Board"));
  const links = element("nav", "page-links");
  links.setAttribute("aria-label", "Pages");
  const here = document.body.dataset.page;
  for (const page of PAGES) {
    const link = element("a", page.title === here ? "current" : "", page.title);
    link.href = page.path;
    if (page.title === here) link.setAttribute("aria-current", "page");
    links.appendChild(link);
  }
  sidebar.appendChild(links);
  // Whether the pipeline is observing sits at the sidebar's foot rather than in the top bar.
  const status = $("status");
  if (status) sidebar.appendChild(status);
  document.body.prepend(sidebar);
  document.body.classList.add("with-sidebar");
}

async function refreshStatus() {
  const status = $("status");
  if (!status) return;
  try {
    const summary = await api("api/summary");
    status.textContent = summary.observing ? "Observing" : "Not observing";
    status.classList.toggle("on", summary.observing);
    status.title = summary.observing
      ? `Observing since ${clockTime(summary.observing_since, false)}. A Press now would be recorded.`
      : "The pipeline is not live. A Press now would be missed.";
    document.dispatchEvent(new CustomEvent("summary", { detail: summary }));
  } catch (error) {
    status.textContent = "Unreachable";
    status.classList.remove("on");
  }
}

// ---- Clip timeline ------------------------------------------------------------

// Draws one Exchange's Words as boxes at their moments in its Clip, above a strip showing its
// Utterances. Returns a function that moves the playhead to a time in the Clip.
function drawClipTimeline(container, exchange, options) {
  container.replaceChildren();
  const hasClip = exchange.clip_started_at !== null;
  const start = hasClip ? exchange.clip_started_at : exchange.started_at - 2;
  const end = hasClip ? exchange.clip_ended_at : exchange.ended_at + 2;
  const length = Math.max(end - start, 1);
  const width = container.clientWidth || 600;
  const place = (time) => Math.min(Math.max((time - start) / length, 0), 1);

  const strip = element("div", "clip-utterances");
  for (const utterance of exchange.utterances) {
    const bar = element("span", `utterance-bar ${utterance.presser}`);
    bar.style.left = `${place(utterance.started_at) * 100}%`;
    bar.style.width = `max(6px, ${(place(utterance.ended_at) - place(utterance.started_at)) * 100}%)`;
    bar.title = `${PRESSER_LABELS[utterance.presser]} Utterance: ${utterance.words.join(" ")}`;
    strip.appendChild(bar);
  }
  container.appendChild(strip);

  // Boxes that would overlap drop to the next row.
  const rowEnds = [];
  const boxes = element("div", "clip-words");
  for (const press of exchange.presses) {
    const box = element("button", `word-box ${press.presser}`, press.word);
    box.type = "button";
    if (press.word_uncertain) box.classList.add("uncertain");
    if (press.id === options.selectedPressId) box.classList.add("selected");
    const left = place(press.pressed_at) * width;
    const boxWidth = 18 + 7.5 * (press.word.length + (press.word_uncertain ? 2 : 0));
    let row = rowEnds.findIndex((rowEnd) => rowEnd <= left);
    if (row === -1) row = rowEnds.length;
    rowEnds[row] = left + boxWidth + 3;
    // A Word at the very end of the Clip is drawn a little early rather than cut off.
    box.style.left = `min(${place(press.pressed_at) * 100}%, calc(100% - ${boxWidth}px))`;
    box.style.top = `${row * 28}px`;
    box.title = `${press.word} at ${clockTime(press.pressed_at)}, ${PRESSER_LABELS[press.presser].toLowerCase()}`;
    box.addEventListener("click", (event) => {
      event.stopPropagation();
      options.onPress(press, press.pressed_at - start);
    });
    boxes.appendChild(box);
  }
  boxes.style.height = `${Math.max(rowEnds.length, 1) * 28}px`;
  container.appendChild(boxes);

  const playhead = element("div", "playhead");
  container.appendChild(playhead);
  container.onclick = (event) => {
    const bounds = container.getBoundingClientRect();
    options.onSeek(((event.clientX - bounds.left) / bounds.width) * length);
  };
  return (clipSeconds) => {
    playhead.style.left = `${Math.min(Math.max(clipSeconds / length, 0), 1) * 100}%`;
  };
}

// Where in its Clip a Press happens, in seconds; null when the Exchange has no Clip yet.
function clipOffset(exchange, press) {
  return exchange.clip_started_at === null ? null : Math.max(press.pressed_at - exchange.clip_started_at, 0);
}

function clipStatusText(exchange) {
  if (exchange.clip_status === "failed") return `No Clip: ${exchange.clip_error || "the recording could not be cut."}`;
  if (exchange.open) return "This Exchange is still going on. Its Clip is cut once it ends.";
  return "The Clip is still being cut from the recording.";
}
