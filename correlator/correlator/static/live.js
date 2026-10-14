"use strict";

// Live Feed: the camera's picture and sound, relayed by Frigate. While the moving picture
// cannot be had, a still from Frigate is shown instead and the connection is retried.
//
// Sound comes on by itself where the browser allows it. Where it does not, the feed starts
// silent and the sound is tried again on a timer until the browser lets it through.
//
// Pause and Resume switch capture off and on at the Pi. While Paused there is nothing to show,
// so no picture is asked for and nothing is retried until Resume.

const RETRY_MS = 4000;
const STILL_REFRESH_MS = 1000;
const STALL_MS = 8000;
const BEHIND_LIVE_SECONDS = 4;
const KEEP_BUFFER_SECONDS = 20;
// Playback stays this far behind what has arrived, so an uneven stream does not freeze it.
const CUSHION_SECONDS = 1.2;
const SOUND_CHOICE_KEY = "fluentpet.live.sound";
// How often the sound is tried again while the browser is making the feed play silently.
const SOUND_RETRY_SECONDS = 2;
// How often the Pi is asked whether it is Paused, so a Pause made elsewhere shows here too.
const CAPTURE_REFRESH_MS = 5000;
const CAPTURE_LABELS = {
  live: "Pause",
  starting: "Starting…",
  down: "Pause",
  paused: "Resume",
  unreachable: "Can't reach the Pi",
  error: "Pause unavailable",
};
// What go2rtc is asked for; only the ones this browser can play are sent.
const CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0", "mp4a.40.2", "mp4a.40.5", "flac", "opus"];

const video = $("video");
const still = $("still");
let socket = null;
let address = null; // where the stream is, once the Correlator has said
let retryTimer = null;
let retryAtOnce = false;
let lastData = 0;
let wantSound = readSoundChoice();
let starting = false;
let soundTries = 0; // since the feed last had to start silently
let refilling = false; // paused after running dry, until the cushion is back
let capture = null; // the Pi's last answer about capture; null until it has given one
// Kept apart from that answer: losing touch with the Pi does not end a Pause.
let paused = false;
let switching = false; // a Pause or Resume is on its way to the Pi

// An iPhone has no MediaSource, only this close relative of it (iOS 17.1 and later).
const SourceType = window.MediaSource || window.ManagedMediaSource;

function streamAddress(live) {
  if (live.stream_url) return live.stream_url;
  const source = `/live/mse/api/ws?src=${encodeURIComponent(live.camera)}`;
  // Over HTTPS the page is being forwarded from the PC, and Frigate's stream is forwarded
  // beside it at the same address. Otherwise this is the PC itself, where Frigate is on port 5000.
  if (location.protocol === "https:") return `wss://${location.host}${source}`;
  return `ws://${location.hostname}:5000${source}`;
}

function setFeedState(text) {
  $("feed-state").textContent = text;
}

function showStill(show) {
  still.hidden = !show;
  video.hidden = show;
}

// ---- Sound --------------------------------------------------------------------

function readSoundChoice() {
  try {
    return localStorage.getItem(SOUND_CHOICE_KEY) !== "off";
  } catch (error) {
    return true; // Storage can be blocked; sound is wanted unless it was turned off.
  }
}

function keepSoundChoice() {
  try {
    localStorage.setItem(SOUND_CHOICE_KEY, wantSound ? "on" : "off");
  } catch (error) {
    // The choice then lasts only until the page is closed.
  }
}

function showSound() {
  $("sound").textContent = video.muted ? "Sound off" : "Sound on";
  $("sound").title = video.muted ? "Turn the sound on (M)" : "Turn the sound off (M)";
  $("sound").classList.toggle("on", !video.muted);
}

function setSound(on) {
  wantSound = on;
  keepSoundChoice();
  video.muted = !on;
  if (on && !refilling) video.play().catch(() => {});
  showSound();
}

// Starts the picture with sound if the browser allows it, and silently if it does not.
async function startPlaying() {
  if (starting || refilling || !video.paused || ahead() < CUSHION_SECONDS) return;
  starting = true;
  try {
    video.muted = !wantSound;
    await video.play();
  } catch (error) {
    if (error.name === "NotAllowedError") {
      video.muted = true;
      await video.play().catch(() => {});
      soundTries = 0;
    }
  } finally {
    starting = false;
    showSound();
  }
}

async function turnSoundOn() {
  if (!wantSound || !video.muted || video.paused || starting || refilling) return;
  // A refused try makes the feed stumble. After the first, wait until the browser says it would allow one.
  if (soundTries > 0 && !(navigator.userActivation && navigator.userActivation.hasBeenActive)) return;
  soundTries += 1;
  video.muted = false;
  try {
    // A browser that still refuses pauses the feed here, so playing it again is the test.
    await video.play();
  } catch (error) {
    video.muted = true;
    video.play().catch(() => {});
  } finally {
    showSound();
  }
}

// ---- The stream ---------------------------------------------------------------

function connect() {
  retryTimer = null;
  if (isPaused()) return;
  if (!SourceType) {
    setFeedState("This browser cannot play the live stream, so a still picture is shown.");
    showStill(true);
    return;
  }
  const mediaSource = new SourceType();
  const waiting = [];
  let buffer = null;
  // The iPhone's kind only opens once the video is told not to offer AirPlay.
  video.disableRemotePlayback = true;
  video.src = URL.createObjectURL(mediaSource);

  const feed = () => {
    if (!buffer || buffer.updating || !waiting.length) return;
    try {
      buffer.appendBuffer(waiting.shift());
    } catch (error) {
      socket.close();
    }
  };

  socket = new WebSocket(address);
  socket.binaryType = "arraybuffer";
  socket.addEventListener("open", () => {
    const playable = CODECS.filter((codec) => SourceType.isTypeSupported(`video/mp4; codecs="${codec}"`));
    const ask = () => socket.send(JSON.stringify({ type: "mse", value: playable.join(",") }));
    if (mediaSource.readyState === "open") ask();
    else mediaSource.addEventListener("sourceopen", ask, { once: true });
  });
  socket.addEventListener("message", (event) => {
    lastData = Date.now();
    if (typeof event.data === "string") {
      const message = JSON.parse(event.data);
      if (message.type === "mse") {
        buffer = mediaSource.addSourceBuffer(message.value);
        buffer.mode = "segments";
        buffer.addEventListener("updateend", () => {
          trim(buffer);
          feed();
          resumeWhenRefilled();
        });
      } else if (message.type === "error") {
        // Frigate is up but has no stream to pass on, which is what a camera that is off looks like.
        console.warn("Frigate could not send the stream:", message.value);
        socket.close();
      }
      return;
    }
    waiting.push(event.data);
    feed();
    if (video.hidden || still.hidden === false) showStill(false);
    setFeedState("Live");
    startPlaying();
  });
  socket.addEventListener("close", () => {
    refilling = false;
    if (isPaused()) return; // closed on purpose, and not to be retried
    setFeedState("No live stream: the camera or Frigate is not sending. Trying again…");
    showStill(true);
    retryTimer = setTimeout(connect, retryAtOnce ? 0 : RETRY_MS);
    retryAtOnce = false;
  });
}

// Finds the stream and connects to it.
async function begin() {
  try {
    address = streamAddress(await api("api/live"));
    clearProblem();
    connect();
  } catch (error) {
    showProblem(error);
  }
}

// After a pause the old connection is dead but may not have noticed. Rather than wait for it
// to be found stalled, a new one is made straight away.
function reconnectNow() {
  if (!address) {
    begin();
  } else if (retryTimer !== null) {
    clearTimeout(retryTimer);
    connect();
  } else if (socket && socket.readyState !== WebSocket.CLOSED && Date.now() - lastData > STILL_REFRESH_MS * 2) {
    retryAtOnce = true;
    socket.close();
  }
}

// How many seconds have arrived beyond what is being shown.
function ahead() {
  if (!video.buffered.length) return 0;
  return video.buffered.end(video.buffered.length - 1) - video.currentTime;
}

// Running dry freezes the picture. Rather than stutter along the edge of what has arrived,
// playback waits here for the cushion and then carries on.
function refill() {
  if (refilling || video.paused) return;
  refilling = true;
  video.pause();
}

function resumeWhenRefilled() {
  if (!refilling || ahead() < CUSHION_SECONDS) return;
  refilling = false;
  startPlaying();
}

// Drops what has already been watched, and catches up if playback has fallen behind.
function trim(buffer) {
  if (buffer.updating || !video.buffered.length) return;
  const newest = video.buffered.end(video.buffered.length - 1);
  const oldest = video.buffered.start(0);
  if (newest - video.currentTime > BEHIND_LIVE_SECONDS) video.currentTime = newest - CUSHION_SECONDS;
  if (video.currentTime - oldest > KEEP_BUFFER_SECONDS) {
    try {
      buffer.remove(oldest, video.currentTime - KEEP_BUFFER_SECONDS / 2);
    } catch (error) {
      // Nothing is lost if this round of tidying is skipped.
    }
  }
}

// ---- Pause and Resume ---------------------------------------------------------

function isPaused() {
  return paused;
}

// Asks the Correlator, which asks the Pi. Always gives back a state: the Pi's own, or why there is none.
async function askCapture(path, options) {
  let reply;
  try {
    reply = await fetch(path, options);
  } catch (error) {
    return { state: "unreachable", error: "The Correlator's web service cannot be reached." };
  }
  let body = null;
  try {
    body = await reply.json();
  } catch (error) {
    // Handled below, as a failure.
  }
  if (reply.status === 404 && !options) return { state: "not-set-up" };
  if (reply.ok && body && body.state) return body;
  if (body && body.state === "unreachable") return body;
  return { state: "error", error: (body && body.error) || `The request failed (${reply.status}).` };
}

async function refreshCapture() {
  if (switching) return;
  showCapture(await askCapture("api/capture"));
}

async function switchCapture() {
  if (switching || capture === null) return;
  const action = paused ? "resume" : "pause";
  switching = true;
  $("capture").disabled = $("resume").disabled = true;
  $("capture").textContent = action === "pause" ? "Pausing…" : "Resuming…";
  $("resume").textContent = "Resuming…";
  const answer = await askCapture(`api/capture/${action}`, { method: "POST" });
  switching = false;
  if (answer.state === "error" || answer.state === "unreachable") {
    showProblem(new Error(`Could not ${action}: ${answer.error}`));
    await refreshCapture(); // shows what the Pi is actually doing
    return;
  }
  clearProblem();
  showCapture(answer);
}

function pausedSinceText(since) {
  if (!since) return "Since an unknown time.";
  const when = new Date(since * 1000);
  const time = clockTime(since, false);
  if (isoDate(when) === isoDate(new Date())) return `Since ${time} today.`;
  return `Since ${time} on ${when.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}.`;
}

function showCapture(next) {
  const wasPaused = paused;
  const known = !["unreachable", "error"].includes(next.state);
  capture = next;
  if (known) paused = next.state === "paused";
  const usable = !switching && ["live", "down", "paused"].includes(next.state);

  const button = $("capture");
  button.hidden = next.state === "not-set-up";
  button.textContent = CAPTURE_LABELS[next.state] || "Pause";
  button.disabled = !usable;
  button.classList.toggle("resume", next.state === "paused");
  if (next.error) button.title = next.error;
  else button.title = paused ? "Turn the camera and mic back on" : "Turn the camera and mic off at the Pi";
  $("resume").disabled = !usable;
  $("resume").textContent = usable || switching ? "Resume" : "Can't reach the Pi";

  if (paused) {
    if (next.state === "paused") $("paused-since").textContent = pausedSinceText(next.since);
    if (!wasPaused) stopFeed();
    setFeedState("Paused");
  } else if (wasPaused) {
    // Resumed, here or elsewhere: the stream takes a few seconds to come back.
    $("paused").hidden = true;
    setFeedState("Resumed: waiting for the stream…");
    if (address) connect();
    else begin();
  }
}

// Lets go of the stream and shows the Paused panel in place of the picture.
function stopFeed() {
  if (retryTimer !== null) clearTimeout(retryTimer);
  retryTimer = null;
  if (socket && socket.readyState !== WebSocket.CLOSED) socket.close();
  video.pause();
  video.removeAttribute("src");
  video.load();
  video.hidden = true;
  still.hidden = true;
  $("paused").hidden = false;
}

async function start() {
  setUpHeader();
  $("sound").addEventListener("click", () => setSound(video.muted));
  setInterval(turnSoundOn, SOUND_RETRY_SECONDS * 1000);
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.key.toLowerCase() !== "m") return;
    setSound(video.muted);
  });
  video.addEventListener("volumechange", showSound);
  video.addEventListener("waiting", refill);
  showSound();

  setInterval(() => {
    if (!still.hidden) still.src = `live.jpg?at=${Date.now()}`;
    // A stream that stops sending without closing is closed here, so it is retried.
    if (socket && socket.readyState === WebSocket.OPEN && lastData && Date.now() - lastData > STALL_MS) socket.close();
  }, STILL_REFRESH_MS);

  $("capture").addEventListener("click", switchCapture);
  $("resume").addEventListener("click", switchCapture);
  setInterval(refreshCapture, CAPTURE_REFRESH_MS);
  onWake(() => {
    refreshCapture();
    reconnectNow();
  });
  // Whether the Pi is Paused is known before any picture is asked for.
  await refreshCapture();
  await begin();
}

start();
