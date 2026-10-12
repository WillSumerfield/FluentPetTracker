"use strict";

// Metrics: the study's figures for one period, with the cat and the human always side by side
// in separate charts, never mixed into one.

const PRESSERS = ["cat", "human"];
const WHO = { cat: "The cat", human: "Humans" };
const SVG = "http://www.w3.org/2000/svg";

const TREND_MEASURES = [
  { key: "words_per_day", label: "Words per day" },
  { key: "words", label: "Words" },
  { key: "utterances", label: "Utterances" },
  { key: "mean_length", label: "Mean Utterance length" },
  { key: "longest", label: "Longest Utterance" },
  { key: "vocabulary", label: "Different Words so far" },
];

const state = {
  period: "week",
  date: null, // any day inside the period shown; null is today
  data: null,
  trend: "words_per_day",
};

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

// A grid of how often the Word of each row is followed by the Word of each column.
function transitionGrid(transitions, presser) {
  const words = transitions.words;
  const top = Math.max(0, ...transitions.counts.flat());
  if (!top) return element("p", "empty", "No Utterance in this period has two Words.");
  const table = element("table", "grid");
  const head = element("tr");
  head.appendChild(element("th", "corner", "first ↓  then →"));
  for (const word of words) head.appendChild(element("th", "", word));
  table.appendChild(head);
  words.forEach((word, row) => {
    const line = element("tr");
    line.appendChild(element("th", "", word));
    transitions.counts[row].forEach((count, column) => {
      const cell = element("td", count ? `heat ${presser}` : "", count ? String(count) : "");
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

// ---- Sections -----------------------------------------------------------------

// One section of the page: a heading, then the same chart for the cat and for the human.
function section(title, note, draw) {
  const block = element("section", "metric");
  block.appendChild(element("h2", "", title));
  if (note) block.appendChild(element("p", "hint", note));
  const pair = element("div", "pair");
  for (const presser of PRESSERS) {
    const card = element("div", "card");
    card.appendChild(element("h3", presser, WHO[presser]));
    card.append(...[].concat(draw(state.data[presser], presser)));
    pair.appendChild(card);
  }
  block.appendChild(pair);
  return block;
}

function renderSections() {
  const data = state.data;
  const trendMeasure = TREND_MEASURES.find((measure) => measure.key === state.trend);
  const unit = { day: "days", week: "weeks", month: "months" }[data.trend_unit];
  const sections = $("sections");
  sections.replaceChildren();

  sections.appendChild(
    section("Utterances", null, (who, presser) => [
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
    ]),
  );

  sections.appendChild(
    section("Utterance length", "How many Utterances had each number of Words.", (who, presser) =>
      barChart(who.length.histogram, presser, "No Utterances in this period."),
    ),
  );

  const trend = section(
    `Trend: ${trendMeasure.label.toLowerCase()}`,
    `The last ${data.trend_labels.length} ${unit}, ending with the one shown.`,
    (who, presser) => lineChart(data.trend_labels, who.trend.map((point) => point[state.trend]), presser),
  );
  const chooser = element("div", "range");
  for (const measure of TREND_MEASURES) {
    const button = element("button", measure.key === state.trend ? "active" : "", measure.label);
    button.addEventListener("click", () => {
      state.trend = measure.key;
      renderSections();
    });
    chooser.appendChild(button);
  }
  trend.insertBefore(chooser, trend.querySelector(".pair"));
  sections.appendChild(trend);

  sections.appendChild(
    section("Time between Words", "The pause from one Press to the next inside an Utterance.", (who, presser) => [
      figures([[duration(who.word_gaps.median), "median"], [duration(who.word_gaps.mean), "mean"]]),
      barChart(who.word_gaps.histogram, presser, "No Utterance in this period has two Words."),
    ]),
  );

  sections.appendChild(
    section(
      "Time between Utterances",
      "From the end of one Utterance to the start of the same Presser's next. Pauses that span a break in observation are left out.",
      (who, presser) => [
        figures([[duration(who.utterance_gaps.median), "median"], [duration(who.utterance_gaps.mean), "mean"]]),
        barChart(who.utterance_gaps.histogram, presser, "Fewer than two Utterances to measure between."),
      ],
    ),
  );

  sections.appendChild(
    section("Word frequency", "How often each Word was pressed, most used first.", (who, presser) =>
      rankedBars(
        who.word_frequency.map((row) => ({ label: wordChip(row.word, presser), value: row.count, text: String(row.count) })),
        presser,
        "No Words in this period.",
      ),
    ),
  );

  sections.appendChild(
    section("Most common phrases", "Whole Utterances, counted by how often exactly that sequence was pressed.", (who, presser) =>
      rankedBars(
        who.phrases.map((row) => ({ label: phraseChips(row.words, presser), value: row.count, text: String(row.count) })),
        presser,
        "No Utterances in this period.",
      ),
    ),
  );

  sections.appendChild(
    section("Utterance length by Word", "The mean length of the Utterances each Word appears in.", (who, presser) =>
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
    ),
  );

  sections.appendChild(
    section("Repetition", "Utterances in which a Word is pressed again straight after itself.", (who, presser) => [
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
    ]),
  );

  sections.appendChild(
    section("Time of day", "Words pressed in each hour of the day.", (who, presser) =>
      barChart(
        who.by_hour.map((count, hour) => ({ label: hour % 3 === 0 ? String(hour).padStart(2, "0") : "", count, title: `${String(hour).padStart(2, "0")}:00 – ${count}` })),
        presser,
        "No Words in this period.",
      ),
    ),
  );

  sections.appendChild(
    section("Word to Word", "How often one Word is followed by another inside an Utterance, for the most used Words.", (who, presser) =>
      transitionGrid(who.transitions, presser),
    ),
  );

  const minutes = Math.round(data.response_seconds / 60);
  sections.appendChild(
    section(
      "Call and response",
      `An Utterance counts as a reply when it is the next one said after the other Presser's, within ${minutes} minutes.`,
      (who, presser) => [
        figures([
          [number(who.replies.count), presser === "cat" ? "replies to a human" : "replies to the cat"],
          [percent(who.replies.share), "of their Utterances"],
          [duration(who.replies.median_delay), "median delay"],
        ]),
        replyList(who.replies.top, presser),
      ],
    ),
  );

  sections.appendChild(
    section("Vocabulary", null, (who, presser) => [
      element("h4", "", "New in this period"),
      wordList(who.new_words, presser, "No Word was used for the first time."),
      element("h4", "", "Used before, but not in this period"),
      wordList(who.dropped_words, presser, data.period === "all" ? "Does not apply to the whole study." : "None."),
      element("h4", "", "First use of each Word"),
      firstUses(who.first_uses, presser),
    ]),
  );
}

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

  const notes = [`${data.observed_hours} hours observed.`];
  if (data.period !== "day") {
    notes.push(
      `${data.counted_days} of ${plural(data.days_in_period, "day")} were observed for more than ${data.counted_day_hours} hours and count towards per-day figures.`,
    );
  } else if (!data.counted_days) {
    notes.push(`Observed for ${data.counted_day_hours} hours or less, so this day has no per-day figure.`);
  }
  if (data.undecided_presses) {
    notes.push(
      `${plural(data.undecided_presses, "Ambiguous Press", "Ambiguous Presses")} in ${plural(data.undecided_utterances, "Utterance")} await review and are in neither column.`,
    );
  }
  $("period-note").textContent = notes.join(" ");
  renderSections();
}

function start() {
  setUpHeader();
  for (const button of document.querySelectorAll("#periods button")) {
    button.addEventListener("click", () => {
      state.period = button.dataset.period;
      load();
    });
  }
  $("period-previous").addEventListener("click", () => {
    state.date = state.data.previous;
    load();
  });
  $("period-next").addEventListener("click", () => {
    state.date = state.data.next;
    load();
  });
  load();
}

start();
