"use strict";

// Clips: every Clip in a range of months, a day to a row, newest day first. A strip of bars
// counts them by day; a Clip opens over the grid to be watched.

const REFRESH_MS = 60000;
const MOST_MONTHS = 12; // as the web service allows
const LINES_PER_TILE = 3; // Utterances named on a tile before "+2 more"
const SOUND_CHOICE_KEY = "fluentpet.clips.sound";
const MONTH_NAMES = { month: "short", year: "numeric" };

const state = {
  data: null, // the last answer from api/clips
  answer: "", // the same, as text, to tell whether a refresh changed anything
  from: null, // "2026-10"
  to: null,
  filters: { pet: false, review: false, word: "" },
  shown: [], // the Clips passing the filters, oldest first: the order the viewer steps through
  open: null, // the Exchange in the viewer
  openedFrom: null, // the tile to return focus to
  daysInView: new Set(),
  movePlayhead: () => {},
};

const video = $("video");
const viewer = $("viewer");
let wantSound = readSoundChoice();
let dayObserver = null;

// ---- Months -------------------------------------------------------------------

function monthOf(isoDay) {
  return isoDay.slice(0, 7);
}

function monthName(month) {
  const [year, number] = month.split("-").map(Number);
  return new Date(year, number - 1, 1).toLocaleDateString([], MONTH_NAMES);
}

function shiftMonth(month, by) {
  const [year, number] = month.split("-").map(Number);
  const moved = new Date(year, number - 1 + by, 1);
  return `${moved.getFullYear()}-${String(moved.getMonth() + 1).padStart(2, "0")}`;
}

function monthsBetween(first, last) {
  const [y1, m1] = first.split("-").map(Number);
  const [y2, m2] = last.split("-").map(Number);
  return (y2 - y1) * 12 + (m2 - m1) + 1;
}

// Both pickers list every month from the first Clip to this one.
function fillMonthPickers(firstDay, today) {
  const months = [];
  for (let month = monthOf(firstDay); month <= monthOf(today); month = shiftMonth(month, 1)) months.push(month);
  // A month asked for in the address is listed even when it holds nothing.
  for (const month of [state.from, state.to]) if (!months.includes(month)) months.push(month);
  months.sort();
  for (const picker of [$("month-from"), $("month-to")]) {
    const chosen = picker === $("month-from") ? state.from : state.to;
    picker.replaceChildren(
      ...months.map((month) => {
        const option = element("option", "", monthName(month));
        option.value = month;
        option.selected = month === chosen;
        return option;
      }),
    );
  }
}

function chooseMonths(from, to, moved) {
  // The other end follows, so the range is never backwards and never too long.
  if (moved === "from") {
    if (to < from) to = from;
    if (monthsBetween(from, to) > MOST_MONTHS) to = shiftMonth(from, MOST_MONTHS - 1);
  } else {
    if (from > to) from = to;
    if (monthsBetween(from, to) > MOST_MONTHS) from = shiftMonth(to, -(MOST_MONTHS - 1));
  }
  state.from = from;
  state.to = to;
  rememberInAddress();
  load();
}

// ---- Loading ------------------------------------------------------------------

async function load() {
  try {
    const answer = await api(`api/clips?from=${state.from}&to=${state.to}`);
    clearProblem();
    const text = JSON.stringify(answer);
    if (text === state.answer) return;
    state.answer = text;
    state.data = answer;
    fillMonthPickers(answer.first_day, answer.today);
    fillWordPicker(answer.words);
    render();
  } catch (error) {
    showProblem(error);
  }
}

function fillWordPicker(words) {
  const picker = $("filter-word");
  const chosen = state.filters.word;
  const options = [element("option", "", "Any Word")];
  options[0].value = "";
  for (const word of words) {
    const option = element("option", "", word);
    option.value = word;
    options.push(option);
  }
  picker.replaceChildren(...options);
  picker.value = words.includes(chosen) ? chosen : "";
  state.filters.word = picker.value;
  picker.classList.toggle("chosen", Boolean(picker.value));
}

// ---- Filters ------------------------------------------------------------------

function passes(clip) {
  const { pet, review, word } = state.filters;
  if (pet && !clip.pet_spoke) return false;
  if (review && !clip.awaiting_review) return false;
  if (word && !clip.utterances.some((utterance) => utterance.words.includes(word))) return false;
  return true;
}

function setFilter(name, value) {
  state.filters[name] = value;
  const button = { pet: $("filter-pet"), review: $("filter-review") }[name];
  if (button) button.setAttribute("aria-pressed", String(value));
  $("filter-word").classList.toggle("chosen", Boolean(state.filters.word));
  render();
}

// ---- Drawing ------------------------------------------------------------------

function render() {
  if (!state.data) return;
  const days = state.data.days
    .map((day) => ({ date: day.date, clips: day.clips.filter(passes) }))
    .filter((day) => day.clips.length);
  state.shown = days
    .slice()
    .reverse()
    .flatMap((day) => day.clips);

  const clipCount = state.shown.length;
  $("total").textContent = clipCount ? `${plural(clipCount, "Clip")} on ${plural(days.length, "day")}` : "";
  drawStrip(days);
  drawDays(days);

  const filtered = state.filters.pet || state.filters.review || state.filters.word;
  const empty = $("empty");
  empty.hidden = clipCount > 0;
  if (!clipCount) {
    const months = state.from === state.to ? monthName(state.from) : `${monthName(state.from)} to ${monthName(state.to)}`;
    empty.textContent = filtered
      ? `No Clip in ${months} matches. Turn a filter off to see more.`
      : `No Clips in ${months}. Choose other months above.`;
  }
}

// One bar per day of the range: its height is the day's Clips, the part the Pet spoke in shaded.
function drawStrip(days) {
  const strip = $("days-strip");
  const axis = $("days-axis");
  const counts = new Map(days.map((day) => [day.date, day.clips]));
  const most = Math.max(1, ...days.map((day) => day.clips.length));
  const first = state.data.from;
  const last = state.data.to;
  const single = state.from === state.to;
  const total = Math.round((new Date(`${last}T12:00`) - new Date(`${first}T12:00`)) / 86400000) + 1;
  const columns = [];
  const labels = [];
  let index = 0;
  for (let day = first; day <= last; day = shiftDay(day, 1), index += 1) {
    const clips = counts.get(day) || [];
    const column = element("button", "day-bar");
    column.type = "button";
    column.dataset.day = day;
    if (day > state.data.today) column.classList.add("future");
    if (!clips.length) column.disabled = true;
    if (state.daysInView.has(day)) column.classList.add("in-view");
    const spoke = clips.filter((clip) => clip.pet_spoke).length;
    const all = element("span", "day-bar-all");
    all.style.height = clips.length ? `max(3px, ${(clips.length / most) * 100}%)` : "0";
    const pet = element("span", "day-bar-pet");
    pet.style.height = clips.length ? `${(spoke / clips.length) * 100}%` : "0";
    all.appendChild(pet);
    column.appendChild(all);
    column.setAttribute(
      "aria-label",
      `${dayName(day)}: ${plural(clips.length, "Clip")}, ${spoke} with ${PET_NAME} speaking`,
    );
    columns.push(column);

    const date = Number(day.slice(8));
    if (single ? [1, 8, 15, 22, 29].includes(date) : date === 1) {
      const label = element("span", "", single ? String(date) : monthName(monthOf(day)));
      label.style.gridColumn = `${index + 1} / span ${Math.min(single ? 7 : 28, total - index)}`;
      labels.push(label);
    }
  }
  strip.style.setProperty("--days", total);
  strip.classList.toggle("dense", total > 62);
  axis.style.setProperty("--days", total);
  strip.replaceChildren(...columns);
  axis.replaceChildren(...labels);
}

function drawDays(days) {
  if (dayObserver) dayObserver.disconnect();
  state.daysInView.clear();
  const sections = days.map((day) => {
    const section = element("section", "day-section");
    section.id = `day-${day.date}`;
    section.dataset.day = day.date;
    const head = element("header", "day-head");
    head.appendChild(element("h2", "", dayName(day.date)));
    const spoke = day.clips.filter((clip) => clip.pet_spoke).length;
    head.appendChild(
      element("span", "day-count", `${plural(day.clips.length, "Clip")}, ${PET_NAME} spoke in ${spoke}`),
    );
    section.appendChild(head);
    const grid = element("div", "tile-grid");
    for (const clip of day.clips) grid.appendChild(tile(clip));
    section.appendChild(grid);
    return section;
  });
  $("days").replaceChildren(...sections);
  watchDaysInView(sections);
}

function tile(clip) {
  const button = element("button", "clip-tile");
  button.type = "button";
  button.dataset.clip = clip.id;
  const words = clip.utterances.map((utterance) => utterance.words.join(" ")).join(", ");
  button.setAttribute("aria-label", `Clip at ${clockTime(clip.started_at, false)}: ${words}`);

  const picture = element("div", "tile-picture");
  if (clip.ready) {
    const image = element("img");
    image.src = clip.thumbnail_url;
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => image.replaceWith(element("span", "tile-no-picture", "No picture")));
    picture.appendChild(image);
    picture.appendChild(element("span", "tile-length", clipLength(clip.duration)));
  } else {
    picture.classList.add("cutting");
    picture.appendChild(element("span", "tile-no-picture", "Being cut…"));
  }
  button.appendChild(picture);

  const lines = element("div", "tile-words");
  for (const utterance of clip.utterances.slice(0, LINES_PER_TILE)) {
    const line = element("p", `tile-line ${utterance.presser}`);
    for (const word of utterance.words) {
      const span = element("span", word === state.filters.word ? "match" : "", word);
      line.appendChild(span);
      line.appendChild(document.createTextNode(" "));
    }
    lines.appendChild(line);
  }
  const more = clip.utterances.length - LINES_PER_TILE;
  if (more > 0) lines.appendChild(element("p", "tile-more", `+${more} more`));
  button.appendChild(lines);

  const foot = element("div", "tile-foot");
  foot.appendChild(element("span", "tile-time", clockTime(clip.started_at, false)));
  foot.appendChild(element("span", "", plural(clip.presses, "Press", "Presses")));
  if (clip.awaiting_review) foot.appendChild(element("span", "tile-review", "Awaiting review"));
  button.appendChild(foot);

  button.addEventListener("click", () => openClip(clip.id, button));
  return button;
}

function clipLength(seconds) {
  const whole = Math.round(seconds || 0);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

// The bars of the days on screen are marked, so the strip shows where in the range you are.
function watchDaysInView(sections) {
  if (!("IntersectionObserver" in window)) return;
  dayObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const day = entry.target.dataset.day;
      if (entry.isIntersecting) state.daysInView.add(day);
      else state.daysInView.delete(day);
      const bar = document.querySelector(`.day-bar[data-day="${day}"]`);
      if (bar) bar.classList.toggle("in-view", entry.isIntersecting);
    }
  });
  for (const section of sections) dayObserver.observe(section);
}

function goToDay(day) {
  const section = $(`day-${day}`);
  if (!section) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  section.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
}

function setUpStrip() {
  // Each day's heading sticks just under the strip, which is itself stuck to the top.
  const overview = document.querySelector(".overview");
  const measure = () => {
    const stuck = getComputedStyle(overview).position === "sticky";
    document.documentElement.style.setProperty("--overview-height", `${stuck ? overview.offsetHeight : 0}px`);
  };
  if ("ResizeObserver" in window) new ResizeObserver(measure).observe(overview);
  window.addEventListener("resize", measure);
  measure();

  const strip = $("days-strip");
  const tooltip = $("strip-tooltip");
  strip.addEventListener("click", (event) => {
    const bar = event.target.closest(".day-bar");
    if (bar && !bar.disabled) goToDay(bar.dataset.day);
  });
  strip.addEventListener("pointermove", (event) => {
    const bar = event.target.closest(".day-bar");
    if (!bar) {
      tooltip.hidden = true;
      return;
    }
    tooltip.textContent = bar.getAttribute("aria-label");
    tooltip.hidden = false;
    const bounds = $("days-strip").parentElement.getBoundingClientRect();
    const barBounds = bar.getBoundingClientRect();
    const half = tooltip.offsetWidth / 2;
    const centre = barBounds.left + barBounds.width / 2 - bounds.left;
    tooltip.style.left = `${Math.min(Math.max(centre, half + 4), bounds.width - half - 4)}px`;
  });
  strip.addEventListener("pointerleave", () => {
    tooltip.hidden = true;
  });
}

// ---- The viewer ---------------------------------------------------------------

async function openClip(id, fromTile) {
  if (fromTile) state.openedFrom = fromTile;
  let exchange;
  try {
    exchange = await api(`api/exchanges/${id}`);
  } catch (error) {
    showProblem(error);
    return;
  }
  state.open = exchange;
  if (!viewer.open) {
    viewer.showModal();
    // The keys work from the start, without a focus ring on the first button.
    viewer.focus();
  }
  rememberInAddress();

  const day = isoDate(new Date(exchange.started_at * 1000));
  $("viewer-title").textContent = `${dayName(day)}, ${clockTime(exchange.started_at, false)}`;
  const index = state.shown.findIndex((clip) => clip.id === id);
  $("viewer-position").textContent = index >= 0 ? `${index + 1} of ${state.shown.length}` : "";
  $("viewer-previous").disabled = index <= 0;
  $("viewer-next").disabled = index < 0 || index >= state.shown.length - 1;
  const presses = exchange.presses.filter((press) => press.presser !== "discarded").length;
  $("viewer-summary").textContent = `${plural(presses, "Press", "Presses")} in ${plural(
    exchange.utterances.length,
    "Utterance",
  )}`;
  $("open-daily").href = `./?day=${day}&clip=${exchange.id}`;

  if (exchange.clip_url) {
    $("player-message").hidden = true;
    video.hidden = false;
    video.src = exchange.clip_url;
    startPlaying();
  } else {
    video.pause();
    video.removeAttribute("src");
    video.hidden = true;
    $("player-message").hidden = false;
    $("player-message").textContent = clipStatusText(exchange);
  }
  // The strip is drawn once the dialog has a width to draw it in.
  requestAnimationFrame(drawTimeline);
}

function drawTimeline() {
  if (!state.open) return;
  state.movePlayhead = drawClipTimeline($("clip-timeline"), state.open, {
    selectedPressId: null,
    onSeek: (seconds) => {
      if (!video.hidden) video.currentTime = seconds;
    },
    onPress: (press, offset) => {
      if (video.hidden) return;
      video.currentTime = Math.max(offset - 1, 0);
      video.play().catch(() => {});
    },
  });
}

function step(by) {
  if (!state.open) return;
  const index = state.shown.findIndex((clip) => clip.id === state.open.id);
  const next = state.shown[index + by];
  if (index < 0 || !next) return;
  state.openedFrom = document.querySelector(`.clip-tile[data-clip="${next.id}"]`) || state.openedFrom;
  openClip(next.id);
}

function closed() {
  video.pause();
  video.removeAttribute("src");
  video.load();
  // A refresh while the viewer was open draws the tiles again, so the tile is found afresh.
  const id = state.open ? state.open.id : null;
  state.open = null;
  rememberInAddress();
  let back = state.openedFrom;
  if (!back || !document.body.contains(back)) back = document.querySelector(`.clip-tile[data-clip="${id}"]`);
  if (back) {
    back.focus({ preventScroll: true });
    back.scrollIntoView({ block: "nearest" });
  }
}

// ---- Full screen --------------------------------------------------------------

// The video alone goes full screen, with the browser's own controls to scrub and pause.
// iPhones only let a video itself go full screen, through their own call.
function toggleFullscreen() {
  if (video.hidden) return;
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
    return;
  }
  if (video.requestFullscreen) {
    video.controls = true;
    video.requestFullscreen().catch((error) => {
      video.controls = false;
      showProblem(new Error(`Full screen was refused by the browser: ${error.message}`));
    });
  } else if (video.webkitEnterFullscreen) {
    video.webkitEnterFullscreen();
  }
}

// ---- Sound --------------------------------------------------------------------

function readSoundChoice() {
  try {
    return localStorage.getItem(SOUND_CHOICE_KEY) !== "off";
  } catch (error) {
    return true; // Storage can be blocked; sound is wanted unless it was turned off.
  }
}

function setSound(on) {
  wantSound = on;
  try {
    localStorage.setItem(SOUND_CHOICE_KEY, on ? "on" : "off");
  } catch (error) {
    // The choice then lasts only until the page is closed.
  }
  video.muted = !on;
  if (on && !video.hidden) video.play().catch(() => {});
  showSound();
}

// The box shows what is heard, not what is wanted, so it never claims sound the browser is holding back.
function showSound() {
  $("sound").checked = !video.muted;
}

// Plays with sound if the browser allows it, and silently if it does not.
async function startPlaying() {
  try {
    video.muted = !wantSound;
    await video.play();
  } catch (error) {
    if (error.name === "NotAllowedError" && !video.muted) {
      video.muted = true;
      await video.play().catch(() => {});
    }
  } finally {
    showSound();
  }
}

// ---- The address --------------------------------------------------------------

// The months and the open Clip are kept in the address, so a reload or a shared link shows the same.
function rememberInAddress() {
  const params = new URLSearchParams();
  params.set("from", state.from);
  params.set("to", state.to);
  if (state.open) params.set("clip", state.open.id);
  history.replaceState(null, "", `${location.pathname}?${params}`);
}

async function readAddress() {
  const params = new URLSearchParams(location.search);
  const valid = (text) => /^\d{4}-\d{2}$/.test(text || "");
  const thisMonth = monthOf(isoDate(new Date()));
  state.from = valid(params.get("from")) ? params.get("from") : thisMonth;
  state.to = valid(params.get("to")) ? params.get("to") : state.from;
  if (state.to < state.from || monthsBetween(state.from, state.to) > MOST_MONTHS) state.to = state.from;

  const clipId = Number(params.get("clip"));
  if (!Number.isInteger(clipId) || clipId <= 0) return null;
  // A link to a Clip outside the months asked for opens on the Clip's own month.
  if (!valid(params.get("from"))) {
    try {
      const exchange = await api(`api/exchanges/${clipId}`);
      state.from = state.to = monthOf(isoDate(new Date(exchange.started_at * 1000)));
    } catch (error) {
      showProblem(error);
      return null;
    }
  }
  return clipId;
}

// ---- Wiring -------------------------------------------------------------------

async function start() {
  setUpHeader();
  setUpStrip();

  $("month-from").addEventListener("change", (event) => chooseMonths(event.target.value, state.to, "from"));
  $("month-to").addEventListener("change", (event) => chooseMonths(state.from, event.target.value, "to"));
  $("filter-pet").addEventListener("click", () => setFilter("pet", !state.filters.pet));
  $("filter-review").addEventListener("click", () => setFilter("review", !state.filters.review));
  $("filter-word").addEventListener("change", (event) => setFilter("word", event.target.value));

  $("viewer-close").addEventListener("click", () => viewer.close());
  $("viewer-previous").addEventListener("click", () => step(-1));
  $("viewer-next").addEventListener("click", () => step(1));
  viewer.addEventListener("close", closed);
  // A click on the dimmed backdrop, outside the viewer's box, closes it.
  viewer.addEventListener("click", (event) => {
    if (event.target === viewer) viewer.close();
  });
  viewer.addEventListener("keydown", (event) => {
    if (isTyping(event) && event.target.type !== "checkbox") return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === "ArrowLeft") step(-1);
    else if (event.key === "ArrowRight") step(1);
    else if (event.key.toLowerCase() === "m") $("sound").click();
    else if (event.key.toLowerCase() === "f") toggleFullscreen();
    else if (event.key === " " && !video.hidden) {
      if (video.paused) video.play().catch(() => {});
      else video.pause();
    } else return;
    event.preventDefault();
  });

  $("sound").addEventListener("change", (event) => setSound(event.target.checked));
  $("fullscreen").addEventListener("click", toggleFullscreen);
  video.addEventListener("dblclick", toggleFullscreen);
  // Out of full screen the Word strip below is the way to move about, so the controls go again.
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) video.controls = false;
  });
  video.addEventListener("volumechange", showSound);
  video.addEventListener("timeupdate", () => state.movePlayhead(video.currentTime));
  video.addEventListener("click", () => {
    if (video.controls) return; // full screen: the browser's own controls handle the click
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  });
  video.addEventListener("error", () => {
    if (!video.getAttribute("src")) return;
    video.hidden = true;
    $("player-message").hidden = false;
    $("player-message").textContent = "This Clip could not be played. Its file may have been moved or deleted.";
  });

  window.addEventListener("resize", drawTimeline);
  onWake(load);
  setInterval(load, REFRESH_MS);

  const clipId = await readAddress();
  await load();
  if (clipId) openClip(clipId, document.querySelector(`.clip-tile[data-clip="${clipId}"]`));
}

start();
