"""The Correlator's web pages and API, shown inside Home Assistant.

Run with: python -m correlator.web
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from waitress import serve
from werkzeug.exceptions import HTTPException

from .config import Config, ConfigError
from .store import PressNotFound, Store

log = logging.getLogger("correlator.web")

STATIC_DIR = Path(__file__).parent / "static"
MAX_UTTERANCES_PER_REQUEST = 100
SNAPSHOT_TIMEOUT_SECONDS = 3.0


def create_app(config: Config) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    store = Store(config.database_path, config.heartbeat_seconds)
    snapshot_url = f"{config.frigate_url}/api/{config.camera}/latest.jpg?h=540"

    @app.get("/")
    def index() -> Response:
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/summary")
    def summary() -> Response:
        return jsonify(store.summary())

    @app.get("/api/utterances")
    def utterances() -> Response:
        limit = min(_whole_number("limit", 20), MAX_UTTERANCES_PER_REQUEST)
        before = _whole_number("before", 0) or None
        return jsonify(store.utterances(limit, before_id=before))

    @app.get("/api/review-queue")
    def review_queue() -> Response:
        limit = min(_whole_number("limit", 50), MAX_UTTERANCES_PER_REQUEST)
        return jsonify(store.utterances(limit, awaiting_review=True))

    @app.get("/api/history")
    def history() -> Response:
        return jsonify(store.history(_whole_number("days", 30)))

    @app.post("/api/presses/<int:press_id>/review")
    def review(press_id: int) -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "decision" not in body:
            return _problem(400, 'Send JSON such as {"decision": "cat"}.')
        try:
            utterance = store.set_review(press_id, body["decision"])
        except ValueError as error:
            return _problem(400, _sentence(error))
        except PressNotFound as error:
            return _problem(404, _sentence(error))
        log.info("Review Decision on Press %d: %s", press_id, body["decision"] or "withdrawn")
        return jsonify(utterance)

    @app.get("/clips/<int:utterance_id>")
    def clip(utterance_id: int) -> Response:
        clip_path = store.clip_path(utterance_id)
        if clip_path is None:
            return _problem(404, f"Utterance {utterance_id} has no Clip.")
        # conditional=True lets the browser seek within the video.
        return send_from_directory(config.data_dir, clip_path, mimetype="video/mp4", conditional=True)

    @app.get("/live.jpg")
    def live_snapshot() -> Response:
        try:
            with urllib.request.urlopen(snapshot_url, timeout=SNAPSHOT_TIMEOUT_SECONDS) as reply:
                picture = reply.read()
        except (urllib.error.URLError, OSError) as error:
            return _problem(503, f"Frigate gave no picture: {error}")
        return Response(picture, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.errorhandler(sqlite3.Error)
    def database_problem(error: sqlite3.Error) -> Response:
        log.error("The database could not be used: %s", error)
        return _problem(503, "The study's database could not be read. Is the Correlator running?")

    @app.errorhandler(HTTPException)
    def http_problem(error: HTTPException) -> Response:
        return _problem(error.code or 500, error.description or error.name)

    return app


def _whole_number(name: str, default: int) -> int:
    try:
        return max(0, int(request.args.get(name, default)))
    except ValueError:
        return default


def _sentence(error: Exception) -> str:
    message = str(error)
    return message[:1].upper() + message[1:] + "."


def _problem(status: int, message: str) -> Response:
    reply = jsonify({"error": message})
    reply.status_code = status
    return reply


def main() -> int:
    try:
        config = Config.from_environment()
    except ConfigError as error:
        print(f"The Correlator's web pages cannot start: {error}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("Serving the dashboard pages on port %d, reading %s.", config.web_port, config.database_path)
    try:
        serve(create_app(config), host="0.0.0.0", port=config.web_port, threads=8, ident=None)
    except OSError as error:
        log.error("Cannot serve on port %d: %s", config.web_port, error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
