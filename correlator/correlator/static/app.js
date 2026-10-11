"use strict";

const SUMMARY_REFRESH_MS = 5000;
const LIST_REFRESH_MS = 10000;
const SNAPSHOT_REFRESH_MS = 1000;
const PAGE_SIZE = 20;

const DECISION_LABELS = { cat: "Cat", human: "Human", discarded: "Discard" };

const state = {
  tab: "live",
  historyDays: 30,
  lists: { live: [], review: [] },
  expanded: { live: new Set(), review: new Set() },
};

const $ = (id) => document.getElementById(id);

// ---- Helpers ----------------------------------------------------------------

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
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

function showProblem(error) {
  $("notice").textContent = error.message;
  $("notice").hidden = false;
}

function clearProblem() {
  $("notice").hidden = true;
}

function clockTime(seconds) {
  return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function dayAndTime(seconds) {
  const moment = new Date(seconds * 1000);
  const today = new Date().toDateString() === moment.toDateString();
  const day = today ? "Today" : moment.toLocaleDateString([], { day: "numeric", month: "short" });
  return `${day}, ${clockTime(seconds)}`;
}

function hours(value) {
  if (value < 1) return `${Math.round(value * 60)} min`;
  return `${value.toFixed(1)} h`;
}

function number(value) {
  return value === null || value === undefined ? "–" : String(value);
}

// ---- Summary ----------------------------------------------------------------

async function refreshSummary() {
  try {
    const summary = await api("api/summary");
    clearProblem();
    const status = $("status");
    status.classList.toggle("on", summary.observing);
    status.textContent = summary.observing
      ? `Observing since ${clockTime(summary.observing_since)}`
      : "Not observing: the pipeline is not fully live";

    $("tile-cat").textContent = summary.cat_presses_today;
    $("tile-rate").textContent = number(summary.cat_presses_per_hour_today);
    $("tile-observed").textContent = hours(summary.observed_hours_today);
    $("tile-review").textContent = summary.awaiting_review;
    $("tile-vocabulary").textContent = summary.vocabulary_size;
    $("tile-last").textContent = summary.last_cat_word || "–";
    $("tile-last-label").textContent = summary.last_cat_press_at
      ? `last Word by the cat, ${dayAndTime(summary.last_cat_press_at)}`
      : "last Word by the cat";

    const badge = $("review-badge");
    badge.textContent = summary.awaiting_review;
    badge.hidden = summary.awaiting_review === 0;
  } catch (error) {
    $("status").classList.remove("on");
    $("status").textContent = "Disconnected";
    showProblem(error);
  }
}

// ---- Live snapshot ----------------------------------------------------------

function startSnapshot() {
  const picture = $("snapshot");
  const next = () => {
    if (state.tab === "live" && !document.hidden) {
      picture.src = `live.jpg?t=${Date.now()}`;
    } else {
      setTimeout(next, SNAPSHOT_REFRESH_MS);
    }
  };
  picture.addEventListener("load", () => {
    picture.hidden = false;
    $("snapshot-missing").hidden = true;
    setTimeout(next, SNAPSHOT_REFRESH_MS);
  });
  picture.addEventListener("error", () => {
    picture.hidden = true;
    $("snapshot-missing").hidden = false;
    setTimeout(next, 3 * SNAPSHOT_REFRESH_MS);
  });
  next();
}

// ---- Utterances -------------------------------------------------------------

function pressDetail(press) {
  let automatic;
  if (press.automatic_presser === "ambiguous") {
    automatic = press.ambiguity === "both"
      ? "Ambiguous: the cat and the human were both in the Board Zone"
      : "Ambiguous: nobody was seen in the Board Zone";
  } else {
    automatic = `Seen: the ${press.automatic_presser} in the Board Zone`;
  }
  const parts = [clockTime(press.pressed_at), automatic];
  if (press.word_uncertain) parts.push("uncertain Word");
  return parts.join(" · ");
}

function renderChips(container, utterance) {
  container.replaceChildren(
    ...utterance.presses.map((press) => {
      const chip = element("span", `chip ${press.presser}`, press.word);
      if (press.word_uncertain) chip.classList.add("uncertain");
      chip.title = `${press.presser}${press.word_uncertain ? ", uncertain Word" : ""}`;
      return chip;
    }),
  );
}

function renderPresses(container, utterance, listName) {
  container.replaceChildren(
    ...utterance.presses.map((press) => {
      const row = element("div", "press");
      const title = element("div", "press-title");
      title.append(element("span", "press-word", `${press.position}. ${press.word}`));
      title.append(element("span", "press-detail", pressDetail(press)));
      row.append(title);

      const decisions = element("div", "decisions");
      for (const decision of Object.keys(DECISION_LABELS)) {
        const button = element("button", decision, DECISION_LABELS[decision]);
        if (press.review_decision === decision) button.classList.add("chosen");
        button.addEventListener("click", () => decide(listName, press.id, decision, decisions));
        decisions.append(button);
      }
      if (press.review_decision) {
        const undo = element("button", "undo", "Undo");
        undo.title = "Withdraw this Review Decision";
        undo.addEventListener("click", () => decide(listName, press.id, null, decisions));
        decisions.append(undo);
      }
      row.append(decisions);
      return row;
    }),
  );
}

async function decide(listName, pressId, decision, buttons) {
  buttons.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const utterance = await api(`api/presses/${pressId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    clearProblem();
    // Update the card in place, in both lists, so a playing Clip is not interrupted.
    for (const name of Object.keys(state.lists)) {
      const index = state.lists[name].findIndex((entry) => entry.id === utterance.id);
      if (index === -1) continue;
      state.lists[name][index] = utterance;
      const card = document.querySelector(`#${name}-list [data-utterance="${utterance.id}"]`);
      if (card) {
        renderChips(card.querySelector(".chips"), utterance);
        const presses = card.querySelector(".presses");
        if (presses) renderPresses(presses, utterance, name);
      }
    }
    refreshSummary();
  } catch (error) {
    showProblem(error);
    buttons.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function renderBody(utterance, listName) {
  const body = element("div", "utterance-body");
  if (utterance.clip_url) {
    const video = element("video");
    video.src = utterance.clip_url;
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    body.append(video);
  } else {
    const waiting = { waiting: "The Clip is not cut yet.", exporting: "The Clip is being cut." };
    const message = utterance.clip_status === "failed"
      ? `The Clip could not be cut: ${utterance.clip_error || "no reason recorded"}`
      : waiting[utterance.clip_status] || "No Clip.";
    body.append(element("div", "no-clip", message));
  }
  const presses = element("div", "presses");
  renderPresses(presses, utterance, listName);
  body.append(presses);
  return body;
}

function renderList(listName, emptyMessage) {
  const container = $(`${listName}-list`);
  const utterances = state.lists[listName];
  if (utterances.length === 0) {
    container.replaceChildren(element("div", "card empty", emptyMessage));
    return;
  }
  container.replaceChildren(
    ...utterances.map((utterance) => {
      const card = element("article", "card utterance");
      card.dataset.utterance = utterance.id;

      const head = element("button", "utterance-head");
      head.append(element("span", "utterance-time", dayAndTime(utterance.started_at)));
      const chips = element("span", "chips");
      renderChips(chips, utterance);
      head.append(chips);
      head.append(element("span", "utterance-state", utterance.closed_at ? `Utterance ${utterance.id}` : "still open"));
      head.addEventListener("click", () => {
        const expanded = state.expanded[listName];
        const body = card.querySelector(".utterance-body");
        if (body) {
          body.remove();
          expanded.delete(utterance.id);
        } else {
          const current = state.lists[listName].find((entry) => entry.id === utterance.id) || utterance;
          card.append(renderBody(current, listName));
          expanded.add(utterance.id);
        }
      });
      card.append(head);
      if (state.expanded[listName].has(utterance.id)) card.append(renderBody(utterance, listName));
      return card;
    }),
  );
}

async function loadLive() {
  try {
    state.lists.live = await api(`api/utterances?limit=${PAGE_SIZE}`);
    state.expanded.live.clear();
    renderList("live", "No Utterances recorded yet.");
    $("live-more").hidden = state.lists.live.length < PAGE_SIZE;
  } catch (error) {
    showProblem(error);
  }
}

async function loadOlder() {
  const oldest = state.lists.live[state.lists.live.length - 1];
  if (!oldest) return;
  try {
    const older = await api(`api/utterances?limit=${PAGE_SIZE}&before=${oldest.id}`);
    state.lists.live = state.lists.live.concat(older);
    renderList("live", "No Utterances recorded yet.");
    $("live-more").hidden = older.length < PAGE_SIZE;
  } catch (error) {
    showProblem(error);
  }
}

async function loadReview() {
  try {
    state.lists.review = await api("api/review-queue");
    // In the queue, the Clip and the decision buttons are what the reviewer came for.
    state.expanded.review = new Set(state.lists.review.slice(0, 1).map((utterance) => utterance.id));
    renderList("review", "Nothing to review. Every Ambiguous Press has a Review Decision.");
  } catch (error) {
    showProblem(error);
  }
}

// ---- History ----------------------------------------------------------------

function barChart(container, items) {
  const top = Math.max(...items.map((item) => item.value || 0), 0);
  const scaleTop = top > 0 ? top : 1;
  const scale = element("div", "chart-scale");
  scale.append(element("span", "", top > 0 ? String(Math.round(top * 100) / 100) : ""), element("span", "", "0"));

  const bars = element("div", "bars");
  const labels = element("div", "bar-labels");
  const labelEvery = Math.ceil(items.length / 12);
  items.forEach((item, index) => {
    const slot = element("div", "bar-slot");
    slot.title = item.title;
    if (item.unobserved) {
      slot.classList.add("unobserved");
    } else if (item.value > 0) {
      const bar = element("div", "bar");
      bar.style.height = `${Math.max(1, (item.value / scaleTop) * 100)}%`;
      slot.append(bar);
    }
    bars.append(slot);
    labels.append(element("span", "", index % labelEvery === 0 ? item.label : ""));
  });

  const plot = element("div", "chart-plot");
  plot.append(bars, labels);
  container.replaceChildren(scale, plot);
}

function shortDate(isoDate) {
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString([], { day: "numeric", month: "short" });
}

async function loadHistory() {
  document.querySelectorAll("#range button").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.days) === state.historyDays);
  });
  let history;
  try {
    history = await api(`api/history?days=${state.historyDays}`);
  } catch (error) {
    showProblem(error);
    return;
  }

  $("history-totals").textContent =
    `Since ${shortDate(history.first_day)}: ${history.cat_presses} Presses by the cat in ${hours(history.observed_hours)} observed` +
    (history.cat_presses_per_hour === null ? "." : `, ${history.cat_presses_per_hour} per observed hour.`);

  barChart($("chart-days"), history.by_day.map((day) => ({
    label: shortDate(day.date),
    value: day.cat_presses_per_hour,
    unobserved: day.cat_presses_per_hour === null,
    title: day.cat_presses_per_hour === null
      ? `${shortDate(day.date)}: not observed`
      : `${shortDate(day.date)}: ${day.cat_presses_per_hour} per observed hour (${day.cat_presses} Presses in ${hours(day.observed_hours)})`,
  })));

  barChart($("chart-vocabulary"), history.by_day.map((day) => ({
    label: shortDate(day.date),
    value: day.vocabulary_size,
    title: `${shortDate(day.date)}: ${day.vocabulary_size} Words` +
      (day.new_words.length ? `, new: ${day.new_words.join(", ")}` : ""),
  })));

  barChart($("chart-hours"), history.by_hour.map((hour) => ({
    label: `${String(hour.hour).padStart(2, "0")}`,
    value: hour.cat_presses_per_hour,
    unobserved: hour.cat_presses_per_hour === null,
    title: hour.cat_presses_per_hour === null
      ? `${hour.hour}:00: never observed`
      : `${hour.hour}:00: ${hour.cat_presses_per_hour} per observed hour (${hour.cat_presses} Presses in ${hours(hour.observed_hours)})`,
  })));

  const rows = history.words.map((word) => {
    const row = element("tr");
    row.append(
      element("td", "", word.word),
      element("td", "num", String(word.cat)),
      element("td", "num", String(word.human)),
      element("td", "num", String(word.ambiguous)),
      element("td", "", word.last_cat_press_at ? dayAndTime(word.last_cat_press_at) : "–"),
    );
    return row;
  });
  if (rows.length === 0) {
    const row = element("tr");
    const cell = element("td", "empty", "No Presses in this period.");
    cell.colSpan = 5;
    row.append(cell);
    rows.push(row);
  }
  $("words-table").querySelector("tbody").replaceChildren(...rows);
}

// ---- Tabs and timers --------------------------------------------------------

function showTab(tab) {
  state.tab = ["live", "review", "history"].includes(tab) ? tab : "live";
  document.querySelectorAll(".page").forEach((page) => { page.hidden = page.id !== `page-${state.tab}`; });
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.tab);
  });
  if (location.hash !== `#${state.tab}`) history.replaceState(null, "", `#${state.tab}`);
  if (state.tab === "live") loadLive();
  if (state.tab === "review") loadReview();
  if (state.tab === "history") loadHistory();
}

function start() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => showTab(button.dataset.tab));
  });
  document.querySelectorAll("#range button").forEach((button) => {
    button.addEventListener("click", () => {
      state.historyDays = Number(button.dataset.days);
      loadHistory();
    });
  });
  $("live-more").addEventListener("click", loadOlder);
  $("review-reload").addEventListener("click", loadReview);
  window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

  showTab(location.hash.slice(1));
  refreshSummary();
  startSnapshot();
  setInterval(refreshSummary, SUMMARY_REFRESH_MS);
  // The list is left alone while an Utterance is open, so a playing Clip is not interrupted.
  setInterval(() => {
    const showingFirstPage = state.lists.live.length <= PAGE_SIZE;
    if (state.tab === "live" && !document.hidden && state.expanded.live.size === 0 && showingFirstPage) loadLive();
  }, LIST_REFRESH_MS);
}

start();
