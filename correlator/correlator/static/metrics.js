"use strict";

// Metrics: the study's figures for one period, with the cat and the human always side by side
// in separate charts, never mixed into one. The charts are split into groups shown one at a
// time; a search finds one chart, or a Word to highlight in every chart that lists Words.

const PRESSERS = ["cat", "human"];
const WHO = { cat: "The cat", human: "Humans" };
const WHO_LOWER = { cat: "the cat", human: "humans" };
const SVG = "http://www.w3.org/2000/svg";
const PERIODS = ["day", "week", "month", "all"];
const DEFAULT_PERIOD = "week";
const SUGGESTION_LIMIT = 6; // per heading in the search list

const TREND_MEASURES = [
  { key: "words_per_day", label: "Words per day" },
  { key: "words", label: "Words" },
  { key: "utterances", label: "Utterances" },
  { key: "mean_length", label: "Mean Utterance length" },
  { key: "longest", label: "Longest Utterance" },
  { key: "vocabulary", label: "Different Words so far" },
];

// Line icons, 24 units square, drawn in the colour of the text around them.
const ICONS = {
  overview: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
  words: '<path d="M3 18.5 7.5 5.5l4.5 13M4.7 14h5.6"/><circle cx="17.5" cy="15.5" r="3"/><path d="M20.5 12.5v6"/>',
  utterances: '<rect x="2" y="9" width="5.5" height="6" rx="3"/><rect x="9.25" y="9" width="5.5" height="6" rx="3"/><rect x="16.5" y="9" width="5.5" height="6" rx="3"/>',
  timing: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
  replies: '<path d="M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.4-4.4"/>',
};

const GROUPS = [
  { key: "overview", label: "Overview" },
  { key: "words", label: "Words" },
  { key: "utterances", label: "Utterances" },
  { key: "timing", label: "Timing" },
  { key: "replies", label: "Call and response" },
];
const DEFAULT_GROUP = "overview";

const state = {
  period: DEFAULT_PERIOD,
  date: null, // any day inside the period shown; null is today
  data: null,
  trend: "words_per_day",
  view: { kind: "group", key: DEFAULT_GROUP }, // or { kind: "chart", key } or { kind: "word", key }
  lastGroup: DEFAULT_GROUP, // where clearing a search goes back to
  suggestions: [], // what the search list offers now, in order
  active: -1, // which of them the arrow keys are on
};

function icon(name) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name];
  return svg;
}

// ---- Charts -------------------------------------------------------------------

function number(value, unit) {
  if (value === null || value === undefined) return "–";
  return unit ? `${value} ${unit}` : String(value);
}

function percent(share) {
  return share === null || share === undefined ? "–" : `${Math.round(share * 100)}%`;
}

// Upright bars, one per item: { label, count, title }.
function barChart(items, presser, emptyText) {
  if (!items.length || items.every((item) => !item.count)) return element("p", "empty", emptyText || "Nothing to show.");
  const top = Math.max(...items.map((item) => item.count));
  const chart = element("div", "bar-chart");
  chart.style.setProperty("--columns", items.length);
  for (const item of items) {
    const column = element("div", "bar-column");
    column.title = item.title || `${item.label}: ${item.count}`;
    column.appendChild(element("span", "bar-count", item.count ? String(item.count) : ""));
    const bar = element("span", `bar ${presser}`);
    bar.style.height = `${(item.count / top) * 100}%`;
    const slot = element("span", "bar-slot");
    slot.appendChild(bar);
    column.appendChild(slot);
    column.appendChild(element("span", "bar-label", item.label));
    chart.appendChild(column);
  }
  return chart;
}

// Sideways bars with a label on the left: rows of { label (node or text), value, text, title }.
function rankedBars(rows, presser, emptyText) {
  if (!rows.length) return element("p", "empty", emptyText || "Nothing to show.");
  const top = Math.max(...rows.map((row) => row.value)) || 1;
  const list = element("div", "ranked");
  for (const row of rows) {
    const line = element("div", "ranked-row");
    if (row.title) line.title = row.title;
    const label = element("span", "ranked-label");
    label.append(row.label);
    line.appendChild(label);
    const track = element("span", "ranked-track");
    const bar = element("span", `ranked-bar ${presser}`);
    bar.style.width = `${(row.value / top) * 100}%`;
    track.appendChild(bar);
    line.appendChild(track);
    line.appendChild(element("span", "ranked-value", row.text));
    list.appendChild(line);
  }
  return list;
}

// A line across the periods of a trend. Periods with no figure leave a break in the line.
function lineChart(labels, values, presser) {
  if (values.every((value) => value === null || value === undefined)) {
    return element("p", "empty", "No figures for these periods.");
  }
  const width = 600;
  const height = 180;
  const pad = { left: 38, right: 12, top: 12, bottom: 24 };
  const top = Math.max(...values.map((value) => value || 0), 1);
  const x = (index) => pad.left + (labels.length === 1 ? 0.5 : index / (labels.length - 1)) * (width - pad.left - pad.right);
  const y = (value) => pad.top + (1 - value / top) * (height - pad.top - pad.bottom);

  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", `line-chart ${presser}`);
  const add = (tag, attributes, text) => {
    const node = document.createElementNS(SVG, tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    if (text !== undefined) node.textContent = text;
    svg.appendChild(node);
    return node;
  };

  for (const mark of [0, top / 2, top]) {
    add("line", { x1: pad.left, x2: width - pad.right, y1: y(mark), y2: y(mark), class: "grid" });
    add("text", { x: pad.left - 6, y: y(mark) + 4, class: "axis", "text-anchor": "end" }, String(Math.round(mark * 10) / 10));
  }
  const every = Math.ceil(labels.length / 7);
  labels.forEach((label, index) => {
    if ((labels.length - 1 - index) % every === 0) {
      add("text", { x: x(index), y: height - 6, class: "axis", "text-anchor": "middle" }, label);
    }
  });

  let path = "";
  let drawing = false;
  values.forEach((value, index) => {
    if (value === null || value === undefined) {
      drawing = false;
      return;
    }
    path += `${drawing ? "L" : "M"}${x(index)},${y(value)}`;
    drawing = true;
  });
  add("path", { d: path, class: "line" });
  values.forEach((value, index) => {
    if (value === null || value === undefined) return;
    const dot = add("circle", { cx: x(index), cy: y(value), r: index === values.length - 1 ? 4.5 : 3, class: "dot" });
    const title = document.createElementNS(SVG, "title");
    title.textContent = `${labels[index]}: ${value}`;
    dot.appendChild(title);
  });
  return svg;
}

// A grid of how often the Word of each row is followed by the Word of each column. The Word
// searched for has its row and column marked.
function transitionGrid(transitions, presser) {
  const words = transitions.words;
  const top = Math.max(0, ...transitions.counts.flat());
  if (!top) return element("p", "empty", "No Utterance in this period has two Words.");
  const searched = searchedWord();
  const table = element("table", "grid");
  const head = element("tr");
  head.appendChild(element("th", "corner", "first ↓  then →"));
  for (const word of words) head.appendChild(element("th", word === searched ? "match" : "", word));
  table.appendChild(head);
  words.forEach((word, row) => {
    const line = element("tr");
    line.appendChild(element("th", word === searched ? "match" : "", word));
    transitions.counts[row].forEach((count, column) => {
      const cell = element("td", count ? `heat ${presser}` : "", count ? String(count) : "");
      if (searched && (word === searched || words[column] === searched)) cell.classList.add("crossed");
      cell.style.setProperty("--heat", count / top);
      cell.title = `${word} then ${words[column]}: ${count}`;
      line.appendChild(cell);
    });
    table.appendChild(line);
  });
  const holder = element("div", "grid-holder");
  holder.appendChild(table);
  return holder;
}

function figures(pairs) {
  const row = element("div", "figures");
  for (const [value, label, title] of pairs) {
    const figure = element("div", "figure");
    if (title) figure.title = title;
    figure.appendChild(element("span", "figure-value", value));
    figure.appendChild(element("span", "figure-label", label));
    row.appendChild(figure);
  }
  return row;
}

function wordList(words, presser, emptyText) {
  if (!words.length) return element("p", "empty small", emptyText);
  return phraseChips(words, presser);
}

// ---- The charts, and the group each belongs to ---------------------------------

// Every chart on the page. `keywords` help the search find a chart by what it shows rather
// than its exact title; `byWord` charts list Words, so a Word searched for can be found in them.
const SECTIONS = [
  {
    key: "summary",
    group: "overview",
    title: "Utterances",
    keywords: ["summary", "totals", "count", "words", "length", "longest", "mean", "median"],
    draw: (who, presser, data) => [
      figures([
        [number(who.utterances), "Utterances"],
        [number(who.words), "Words"],
        [number(who.words_per_day.mean), "Words per day", `Mean over the ${plural(who.words_per_day.counted_days, "day")} observed for more than ${data.counted_day_hours} hours.`],
        [number(who.distinct_words), "different Words"],
      ]),
      figures([
        [number(who.length.longest), "longest, in Words"],
        [number(who.length.mean), "mean length"],
        [number(who.length.median), "median length"],
        [number(who.length.std_dev), "standard deviation"],
      ]),
      who.length.longest > 1 ? longestLine(who, presser) : "",
    ],
  },
  {
    key: "trend",
    group: "overview",
    title: () => `Trend: ${trendMeasure().label.toLowerCase()}`,
    searchTitle: "Trend",
    keywords: ["over time", "progress", "growth", "line", "history"],
    note: (data) => {
      const unit = { day: "days", week: "weeks", month: "months" }[data.trend_unit];
      return `The last ${data.trend_labels.length} ${unit}, ending with the one shown.`;
    },
    controls: trendChooser,
    draw: (who, presser, data) => lineChart(data.trend_labels, who.trend.map((point) => point[state.trend]), presser),
  },
  {
    key: "word-frequency",
    group: "words",
    title: "Word frequency",
    keywords: ["most used", "popular", "count", "top words"],
    byWord: true,
    note: "How often each Word was pressed, most used first.",
    draw: (who, presser) =>
      rankedBars(
        who.word_frequency.map((row) => ({ label: wordChip(row.word, presser), value: row.count, text: String(row.count) })),
        presser,
        "No Words in this period.",
      ),
  },
  {
    key: "repetition",
    group: "words",
    title: "Repetition",
    keywords: ["repeat", "again", "double"],
    byWord: true,
    note: "Utterances in which a Word is pressed again straight after itself.",
    draw: (who, presser) => [
      figures([[number(who.repetition.utterances), "Utterances with a repeat"], [percent(who.repetition.share), "of all Utterances"]]),
      rankedBars(
        who.repetition.by_word.map((row) => ({
          label: wordChip(row.word, presser),
          value: row.repeated,
          text: `${row.repeated} of ${row.utterances}`,
          title: `Repeated in ${percent(row.share)} of the Utterances it appears in`,
        })),
        presser,
        "No Word was repeated.",
      ),
    ],
  },
  {
    key: "vocabulary",
    group: "words",
    title: "Vocabulary",
    keywords: ["new words", "first use", "dropped", "learned"],
    byWord: true,
    draw: (who, presser, data) => [
      element("h4", "", "New in this period"),
      wordList(who.new_words, presser, "No Word was used for the first time."),
      element("h4", "", "Used before, but not in this period"),
      wordList(who.dropped_words, presser, data.period === "all" ? "Does not apply to the whole study." : "None."),
      element("h4", "", "First use of each Word"),
      firstUses(who.first_uses, presser),
    ],
  },
  {
    key: "length",
    group: "utterances",
    title: "Utterance length",
    keywords: ["histogram", "how long", "number of words"],
    note: "How many Utterances had each number of Words.",
    draw: (who, presser) => barChart(who.length.histogram, presser, "No Utterances in this period."),
  },
  {
    key: "common-utterances",
    group: "utterances",
    title: "Most common Utterances",
    keywords: ["phrases", "sequences", "combinations", "sentences"],
    byWord: true,
    note: "Whole Utterances, counted by how often exactly that sequence was pressed.",
    draw: (who, presser) =>
      rankedBars(
        who.phrases.map((row) => ({ label: phraseChips(row.words, presser), value: row.count, text: String(row.count) })),
        presser,
        "No Utterances in this period.",
      ),
  },
  {
    key: "length-by-word",
    group: "utterances",
    title: "Utterance length by Word",
    keywords: ["mean length", "longer"],
    byWord: true,
    note: "The mean length of the Utterances each Word appears in.",
    draw: (who, presser) =>
      rankedBars(
        who.length_by_word.map((row) => ({
          label: wordChip(row.word, presser),
          value: row.mean_length,
          text: String(row.mean_length),
          title: `In ${plural(row.utterances, "Utterance")}`,
        })),
        presser,
        "No Words in this period.",
      ),
  },
  {
    key: "word-to-word",
    group: "utterances",
    title: "Word to Word",
    keywords: ["transitions", "followed by", "next word", "pairs", "grid", "heatmap"],
    byWord: true,
    note: "How often one Word is followed by another inside an Utterance, for the most used Words.",
    draw: (who, presser) => transitionGrid(who.transitions, presser),
  },
  {
    key: "word-gaps",
    group: "timing",
    title: "Time between Words",
    keywords: ["gap", "pause", "delay", "seconds", "speed"],
    note: "The pause from one Press to the next inside an Utterance.",
    draw: (who, presser) => [
      figures([[duration(who.word_gaps.median), "median"], [duration(who.word_gaps.mean), "mean"]]),
      barChart(who.word_gaps.histogram, presser, "No Utterance in this period has two Words."),
    ],
  },
  {
    key: "utterance-gaps",
    group: "timing",
    title: "Time between Utterances",
    keywords: ["gap", "pause", "delay", "minutes", "how often"],
    note: "From the end of one Utterance to the start of the same Presser's next. Pauses that span a break in observation are left out.",
    draw: (who, presser) => [
      figures([[duration(who.utterance_gaps.median), "median"], [duration(who.utterance_gaps.mean), "mean"]]),
      barChart(who.utterance_gaps.histogram, presser, "Fewer than two Utterances to measure between."),
    ],
  },
  {
    key: "time-of-day",
    group: "timing",
    title: "Time of day",
    keywords: ["hour", "clock", "when", "morning", "evening", "night"],
    note: "Words pressed in each hour of the day.",
    draw: (who, presser) =>
      barChart(
        who.by_hour.map((count, hour) => ({ label: hour % 3 === 0 ? String(hour).padStart(2, "0") : "", count, title: `${String(hour).padStart(2, "0")}:00 – ${count}` })),
        presser,
        "No Words in this period.",
      ),
  },
  {
    key: "call-and-response",
    group: "replies",
    title: "Call and response",
    keywords: ["reply", "replies", "conversation", "answer", "exchange"],
    byWord: true,
    note: (data) =>
      `An Utterance counts as a Reply when it is the next one said after the other Presser's, within ${Math.round(data.response_seconds / 60)} minutes.`,
    draw: (who, presser) => [
      figures([
        [number(who.replies.count), presser === "cat" ? "replies to a human" : "replies to the cat"],
        [percent(who.replies.share), "of their Utterances"],
        [duration(who.replies.median_delay), "median delay"],
      ]),
      replyList(who.replies.top, presser),
    ],
  },
];

const valueOf = (field, data) => (typeof field === "function" ? field(data) : field);
const trendMeasure = () => TREND_MEASURES.find((measure) => measure.key === state.trend);
const groupOf = (key) => GROUPS.find((group) => group.key === key);
const sectionOf = (key) => SECTIONS.find((section) => section.key === key);
const searchedWord = () => (state.view.kind === "word" ? state.view.key : null);

function trendChooser() {
  const chooser = element("div", "range");
  for (const measure of TREND_MEASURES) {
    const button = element("button", measure.key === state.trend ? "active" : "", measure.label);
    button.addEventListener("click", () => {
      state.trend = measure.key;
      renderSections();
    });
    chooser.appendChild(button);
  }
  return chooser;
}

// One section of the page: a heading, then the same chart for the cat and for the human.
function drawSection(definition) {
  const data = state.data;
  const block = element("section", "metric");
  block.appendChild(element("h2", "", valueOf(definition.title, data)));
  const note = valueOf(definition.note, data);
  if (note) block.appendChild(element("p", "hint", note));
  if (definition.controls) block.appendChild(definition.controls());
  const pair = element("div", "pair");
  for (const presser of PRESSERS) {
    const card = element("div", "card");
    card.appendChild(element("h3", presser, WHO[presser]));
    card.append(...[].concat(definition.draw(data[presser], presser, data)));
    pair.appendChild(card);
  }
  block.appendChild(pair);
  return block;
}

// ---- What is shown ------------------------------------------------------------

function sectionsInView() {
  const view = state.view;
  if (view.kind === "chart") return [sectionOf(view.key)];
  if (view.kind === "word") return SECTIONS.filter((section) => section.byWord);
  return SECTIONS.filter((section) => section.group === view.key);
}

function renderSections() {
  if (!state.data) return;
  renderNav();
  const sections = $("sections");
  sections.replaceChildren(...sectionsInView().map(drawSection));
  if (searchedWord()) markWord(sections, searchedWord());
}

function renderNav() {
  const view = state.view;
  for (const button of $("tabs").children) {
    const selected = view.kind === "group" && button.dataset.group === view.key;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected || (view.kind !== "group" && button.dataset.group === state.lastGroup) ? 0 : -1;
  }

  const head = $("view-head");
  head.hidden = view.kind === "group";
  if (view.kind === "chart") {
    const definition = sectionOf(view.key);
    $("view-title").textContent = `${definition.searchTitle || valueOf(definition.title, state.data)} · in ${groupOf(definition.group).label}`;
  } else if (view.kind === "word") {
    $("view-title").textContent = `Charts with “${view.key}”`;
  }
  $("tab-caption").textContent = view.kind === "group" ? groupOf(view.key).label : "";
}

// Highlights the Word wherever a chip shows it, keeps its rows in view inside lists that
// scroll, and says so in any card where it does not appear.
function markWord(container, word) {
  for (const chip of container.querySelectorAll(".chip")) {
    if (chip.textContent !== word) continue;
    chip.classList.add("match");
    const row = chip.closest(".ranked-row, .reply, .first-use");
    if (row) row.classList.add("match-row");
  }
  for (const list of container.querySelectorAll(".ranked, .first-uses")) {
    const first = list.querySelector(".match-row");
    if (!first) continue;
    const offset = first.getBoundingClientRect().top - list.getBoundingClientRect().top;
    list.scrollTop += offset - list.clientHeight / 3;
  }
  for (const card of container.querySelectorAll(".card")) {
    if (card.querySelector(".match")) continue;
    const presser = PRESSERS.find((who) => card.querySelector(`h3.${who}`));
    const missing = element("p", "hint missing", `“${word}” does not appear here for ${WHO_LOWER[presser]} in this period.`);
    card.querySelector("h3").after(missing);
  }
}

// ---- Tabs ---------------------------------------------------------------------

function buildTabs() {
  const tabs = $("tabs");
  for (const group of GROUPS) {
    const button = element("button", "metric-tab");
    button.dataset.group = group.key;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-label", group.label);
    button.title = group.label;
    button.append(icon(group.key), element("span", "tab-label", group.label));
    button.addEventListener("click", () => show({ kind: "group", key: group.key }));
    tabs.appendChild(button);
  }
  // Arrow keys move between the tabs, as in any tab list.
  tabs.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const buttons = [...tabs.children];
    const at = buttons.indexOf(document.activeElement);
    if (at < 0) return;
    const next = buttons[(at + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
    next.focus();
    next.click();
    event.preventDefault();
  });
}

// Shows a tab, one chart or one Word, and records it in the address so Back returns here.
function show(view) {
  state.view = view;
  if (view.kind === "group") state.lastGroup = view.key;
  if (view.kind === "chart") state.lastGroup = sectionOf(view.key).group;
  $("view-note").hidden = true;
  writeAddress(true);
  renderSections();
  window.scrollTo({ top: 0 });
}

// ---- Search -------------------------------------------------------------------

// Every Word either Presser has used in the study, with whether it was pressed in this period.
function knownWords() {
  const pressed = new Set();
  const known = new Set();
  for (const presser of PRESSERS) {
    const who = state.data[presser];
    for (const row of who.word_frequency) pressed.add(row.word);
    for (const use of who.first_uses) known.add(use.word);
  }
  for (const word of pressed) known.add(word);
  return [...known].map((word) => ({ word, pressed: pressed.has(word) }));
}

// Matches beginning with the text come before those merely containing it.
function rank(text, needle) {
  const at = text.toLowerCase().indexOf(needle);
  return at < 0 ? -1 : at === 0 ? 0 : 1;
}

function findSuggestions(query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const charts = SECTIONS.map((definition) => {
    const title = definition.searchTitle || valueOf(definition.title, state.data);
    const ranks = [rank(title, needle), ...definition.keywords.map((keyword) => (rank(keyword, needle) < 0 ? -1 : 2))];
    const best = Math.min(...ranks.filter((value) => value >= 0));
    return { kind: "chart", key: definition.key, label: title, detail: groupOf(definition.group).label, score: best };
  })
    .filter((match) => Number.isFinite(match.score))
    .sort((a, b) => a.score - b.score)
    .slice(0, SUGGESTION_LIMIT);
  const words = knownWords()
    .filter(({ word }) => word.toLowerCase().includes(needle))
    .map(({ word, pressed }) => ({
      kind: "word",
      key: word,
      label: word,
      detail: pressed ? "" : "not pressed this period",
      score: word.toLowerCase() === needle ? -1 : rank(word, needle),
    }))
    .sort((a, b) => a.score - b.score || a.label.localeCompare(b.label))
    .slice(0, SUGGESTION_LIMIT);
  // A Word typed out in full is most likely what was meant, so it leads.
  const exactWord = words.length && words[0].score === -1;
  return exactWord ? [...words, ...charts] : [...charts, ...words];
}

function renderSuggestions() {
  const list = $("suggestions");
  const query = $("search").value.trim();
  list.replaceChildren();
  if (!query) {
    closeSuggestions();
    return;
  }
  state.suggestions = findSuggestions(query);
  state.active = state.suggestions.length ? 0 : -1;
  if (!state.suggestions.length) {
    list.appendChild(element("li", "suggestion-empty", `No chart or Word matches “${query}”.`));
  }
  let heading = null;
  state.suggestions.forEach((match, index) => {
    if (match.kind !== heading) {
      heading = match.kind;
      list.appendChild(element("li", "suggestion-heading", match.kind === "chart" ? "Charts" : "Words"));
    }
    const item = element("li", "suggestion");
    item.id = `suggestion-${index}`;
    item.setAttribute("role", "option");
    if (match.kind === "word") item.append(wordChip(match.label, ""));
    else item.append(icon(sectionOf(match.key).group), element("span", "suggestion-label", match.label));
    if (match.detail) item.appendChild(element("span", "suggestion-detail", match.detail));
    // Pressing down would take the focus from the box and close the list before the click lands.
    item.addEventListener("mousedown", (event) => event.preventDefault());
    item.addEventListener("click", () => pick(match));
    item.addEventListener("mousemove", () => highlightSuggestion(index));
    list.appendChild(item);
  });
  list.hidden = false;
  $("search").setAttribute("aria-expanded", "true");
  highlightSuggestion(state.active);
}

function highlightSuggestion(index) {
  state.active = index;
  for (const item of $("suggestions").querySelectorAll(".suggestion")) {
    const on = item.id === `suggestion-${index}`;
    item.classList.toggle("active", on);
    item.setAttribute("aria-selected", String(on));
    if (on) item.scrollIntoView({ block: "nearest" });
  }
  if (index >= 0) $("search").setAttribute("aria-activedescendant", `suggestion-${index}`);
  else $("search").removeAttribute("aria-activedescendant");
}

function closeSuggestions() {
  $("suggestions").hidden = true;
  $("search").setAttribute("aria-expanded", "false");
  $("search").removeAttribute("aria-activedescendant");
  state.suggestions = [];
  state.active = -1;
}

function pick(match) {
  $("search").value = "";
  closeSuggestions();
  $("search").blur();
  show({ kind: match.kind, key: match.key });
}

function setUpSearch() {
  $("search-icon").appendChild(icon("search"));
  const input = $("search");
  input.addEventListener("input", renderSuggestions);
  input.addEventListener("focus", renderSuggestions);
  input.addEventListener("blur", closeSuggestions);
  input.addEventListener("keydown", (event) => {
    const count = state.suggestions.length;
    if (event.key === "ArrowDown" && count) {
      highlightSuggestion((state.active + 1) % count);
    } else if (event.key === "ArrowUp" && count) {
      highlightSuggestion((state.active - 1 + count) % count);
    } else if (event.key === "Enter") {
      if (state.active >= 0) pick(state.suggestions[state.active]);
    } else if (event.key === "Escape") {
      // First Escape closes the list, a second empties the box.
      if (!$("suggestions").hidden) closeSuggestions();
      else {
        input.value = "";
        input.blur();
      }
    } else {
      return;
    }
    event.preventDefault();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !isTyping(event) && !input.disabled) {
      event.preventDefault();
      input.focus();
    }
  });
  $("view-clear").addEventListener("click", () => show({ kind: "group", key: state.lastGroup }));
}

// ---- The address --------------------------------------------------------------

// The view and the period live after the # (e.g. #word=outside&period=month&date=2026-09-01),
// so a reload, Back and a bookmark all return to exactly what was shown.
function writeAddress(newEntry) {
  const view = state.view;
  const parts = [view.kind === "group" ? view.key : `${view.kind}=${encodeURIComponent(view.key)}`];
  if (state.period !== DEFAULT_PERIOD) parts.push(`period=${state.period}`);
  if (state.date) parts.push(`date=${state.date}`);
  const address = `#${parts.join("&")}`;
  if (address === location.hash) return;
  if (newEntry) history.pushState(null, "", address);
  else history.replaceState(null, "", address);
}

// Reads the address into the state. Returns a note when part of it could not be followed.
function readAddress() {
  const params = new URLSearchParams(location.hash.slice(1));
  const problems = [];

  const period = params.get("period");
  if (period && !PERIODS.includes(period)) problems.push(`period “${period}”`);
  state.period = period && PERIODS.includes(period) ? period : DEFAULT_PERIOD;
  const date = params.get("date");
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) problems.push(`date “${date}”`);
  state.date = date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : null;

  const chart = params.get("chart");
  const word = params.get("word");
  const group = [...params.keys()].find((key) => groupOf(key));
  const other = [...params.keys()].find((key) => !["period", "date", "chart", "word"].includes(key));
  state.view = { kind: "group", key: DEFAULT_GROUP };
  if (chart !== null) {
    if (sectionOf(chart)) state.view = { kind: "chart", key: chart };
    else problems.push(`chart “${chart}”`);
  } else if (word) {
    state.view = { kind: "word", key: word };
  } else if (group) {
    state.view = { kind: "group", key: group };
  } else if (other) {
    problems.push(`tab “${other}”`);
  }
  if (state.view.kind === "group") state.lastGroup = state.view.key;
  if (state.view.kind === "chart") state.lastGroup = sectionOf(state.view.key).group;
  return problems.length ? `The link named an unknown ${problems.join(" and ")}, so the usual view is shown instead.` : null;
}

function followAddress() {
  const before = `${state.period}|${state.date}`;
  const note = readAddress();
  $("view-note").textContent = note || "";
  $("view-note").hidden = !note;
  if (`${state.period}|${state.date}` !== before || !state.data) load();
  else renderSections();
}

// ---- Smaller pieces -----------------------------------------------------------

function longestLine(who, presser) {
  const line = element("p", "hint");
  line.append(`Longest, at ${clockTime(who.length.longest_at, false)}: `, phraseChips(who.length.longest_words, presser));
  return line;
}

function replyList(replies, presser) {
  if (!replies.length) return element("p", "empty", "No replies in this period.");
  const other = presser === "cat" ? "human" : "cat";
  const list = element("div", "replies");
  for (const reply of replies) {
    const row = element("div", "reply");
    row.append(phraseChips(reply.prompt, other), element("span", "arrow", "→"), phraseChips(reply.reply, presser));
    row.appendChild(element("span", "ranked-value", `×${reply.count}`));
    list.appendChild(row);
  }
  return list;
}

function firstUses(uses, presser) {
  if (!uses.length) return element("p", "empty small", "No Words yet.");
  const list = element("div", "first-uses");
  for (const use of uses) {
    const row = element("div", "first-use");
    row.append(wordChip(use.word, presser), element("span", "hint", dayName(isoDate(new Date(use.at * 1000)))));
    list.appendChild(row);
  }
  return list;
}

// ---- Loading ------------------------------------------------------------------

async function load() {
  try {
    const query = `period=${state.period}${state.date ? `&date=${state.date}` : ""}`;
    state.data = await api(`api/metrics?${query}`);
    clearProblem();
  } catch (error) {
    showProblem(error);
    return;
  }
  const data = state.data;
  for (const button of document.querySelectorAll("#periods button")) {
    button.classList.toggle("active", button.dataset.period === state.period);
  }
  $("period-label").textContent = data.label;
  $("period-previous").disabled = !data.previous;
  $("period-next").disabled = !data.next;
  $("search").disabled = false;
  renderSections();
}

// A change of period keeps the view, and replaces the address rather than adding to Back.
function changePeriod(period, date) {
  state.period = period;
  state.date = date;
  writeAddress(false);
  load();
}

function start() {
  setUpHeader();
  buildTabs();
  setUpSearch();
  for (const button of document.querySelectorAll("#periods button")) {
    button.addEventListener("click", () => changePeriod(button.dataset.period, null));
  }
  $("period-previous").addEventListener("click", () => changePeriod(state.period, state.data.previous));
  $("period-next").addEventListener("click", () => changePeriod(state.period, state.data.next));
  // Back, Forward and an address typed by hand all arrive here.
  window.addEventListener("popstate", followAddress);
  onWake(load);
  followAddress();
}

start();
