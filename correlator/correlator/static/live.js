"use strict";

// Live Feed: the camera's picture and sound, relayed by Frigate. While the moving picture
// cannot be had, a still from Frigate is shown instead and the connection is retried.
//
// Sound comes on by itself where the browser allows it. Where it does not, the feed starts
// silent and the sound comes on at the first click or key press anywhere on the page.

const RETRY_MS = 4000;
const STILL_REFRESH_MS = 1000;
const STALL_MS = 8000;
const BEHIND_LIVE_SECONDS = 4;
const KEEP_BUFFER_SECONDS = 20;
// Playback stays this far behind what has arrived, so an uneven stream does not freeze it.
const CUSHION_SECONDS = 1.2;
const SOUND_CHOICE_KEY = "fluentpet.live.sound";
// What go2rtc is asked for; only the ones this browser can play are sent.
const CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0", "mp4a.40.2", "mp4a.40.5", "flac", "opus"];

const video = $("video");
const still = $("still");
let socket = null;
let lastData = 0;
let wantSound = readSoundChoice();
let starting = false;
let refilling = false; // paused after running dry, until the cushion is back

function streamAddress(live) {
  if (live.stream_url) return live.stream_url;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.hostname}:5000/live/mse/api/ws?src=${encodeURIComponent(live.camera)}`;
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
  const waiting = wantSound && video.muted;
  $("sound").textContent = video.muted ? "Sound off" : "Sound on";
  $("sound").title = video.muted ? "Turn the sound on (M)" : "Turn the sound off (M)";
  $("sound").classList.toggle("on", !video.muted);
  $("sound-hint").hidden = !waiting;
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
    }
  } finally {
    starting = false;
    showSound();
  }
}

// The browser's refusal lasts only until the page is first used.
function soundOnFirstUse(event) {
  if (!wantSound || !video.muted || event.target === $("sound")) return;
  if (event.type === "keydown" && event.key.toLowerCase() === "m") return;
  video.muted = false;
  if (!refilling) video.play().catch(() => {});
  showSound();
}

// ---- The stream ---------------------------------------------------------------

function connect(address) {
  if (!("MediaSource" in window)) {
    setFeedState("This browser cannot play the live stream, so a still picture is shown.");
    showStill(true);
    return;
  }
  const mediaSource = new MediaSource();
  const waiting = [];
  let buffer = null;
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
    const playable = CODECS.filter((codec) => MediaSource.isTypeSupported(`video/mp4; codecs="${codec}"`));
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
    setFeedState("No live stream: the camera or Frigate is not sending. Trying again…");
    showStill(true);
    setTimeout(() => connect(address), RETRY_MS);
  });
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

async function start() {
  setUpHeader();
  $("sound").addEventListener("click", () => setSound(video.muted));
  document.addEventListener("click", soundOnFirstUse);
  document.addEventListener("keydown", soundOnFirstUse);
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

  try {
    connect(streamAddress(await api("api/live")));
  } catch (error) {
    showProblem(error);
  }
}

start();
