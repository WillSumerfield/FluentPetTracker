"""The Correlator's web pages and API, shown inside Home Assistant.

Run with: python -m correlator.web
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from waitress import serve
from werkzeug.exceptions import HTTPException

from .config import Config, ConfigError
from .metrics import PERIODS
from .store import NotFound, Store

log = logging.getLogger("correlator.web")

STATIC_DIR = Path(__file__).parent / "static"
SNAPSHOT_TIMEOUT_SECONDS = 3.0


PAGES = {"/": "daily.html", "/review": "review.html", "/live": "live.html", "/metrics": "metrics.html"}


def create_app(config: Config) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    store = Store(config.database_path, config.heartbeat_seconds, config.response_seconds, config.counted_day_hours)
    snapshot_url = f"{config.frigate_url}/api/{config.camera}/latest.jpg?h=720"

    def page(filename: str):
        def show() -> Response:
            return send_from_directory(STATIC_DIR, filename)

        return show

    for path, filename in PAGES.items():
        app.add_url_rule(path, endpoint=filename, view_func=page(filename))

    @app.get("/api/summary")
    def summary() -> Response:
        return jsonify(store.summary())

    @app.get("/api/days/<day>")
    def day(day: str) -> Response:
        try:
            chosen = date.today() if day == "today" else date.fromisoformat(day)
        except ValueError:
            return _problem(400, f"'{day}' is not a date such as 2026-10-12.")
        return jsonify(store.day(chosen))

    @app.get("/api/exchanges/<int:exchange_id>")
    def exchange(exchange_id: int) -> Response:
        try:
            return jsonify(store.exchange(exchange_id))
        except NotFound as error:
            return _problem(404, _sentence(error))

    @app.get("/api/review/next")
    def review_next() -> Response:
        return jsonify(store.next_for_review(_whole_number("after", 0)))

    @app.get("/api/metrics")
    def metrics() -> Response:
        period = request.args.get("period", "week")
        if period not in PERIODS:
            return _problem(400, f"The period must be one of {', '.join(PERIODS)}.")
        try:
            anchor = date.fromisoformat(request.args["date"]) if "date" in request.args else date.today()
        except ValueError:
            return _problem(400, f"'{request.args['date']}' is not a date such as 2026-10-12.")
        return jsonify(store.metrics(period, anchor))

    @app.post("/api/presses/<int:press_id>/review")
    def review_press(press_id: int) -> Response:
        return _review(lambda decision: store.review_press(press_id, decision), f"Press {press_id}")

    @app.post("/api/exchanges/<int:exchange_id>/review")
    def review_exchange(exchange_id: int) -> Response:
        return _review(
            lambda decision: store.review_exchange(exchange_id, decision), f"every Press of Exchange {exchange_id}"
        )

    def _review(record, subject: str) -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or "decision" not in body:
            return _problem(400, 'Send JSON such as {"decision": "cat"}.')
        try:
            changed = record(body["decision"])
        except ValueError as error:
            return _problem(400, _sentence(error))
        except NotFound as error:
            return _problem(404, _sentence(error))
        log.info("Review Decision on %s: %s", subject, body["decision"] or "withdrawn")
        return jsonify(changed)

    @app.get("/clips/<int:exchange_id>")
    def clip(exchange_id: int) -> Response:
        clip_path = store.clip_path(exchange_id)
        if clip_path is None:
            return _problem(404, f"Exchange {exchange_id} has no Clip.")
        # conditional=True lets the browser seek within the video.
        return send_from_directory(config.data_dir, clip_path, mimetype="video/mp4", conditional=True)

    @app.get("/api/live")
    def live() -> Response:
        """Where the Live Feed page finds Frigate's stream. An empty address means the page works it out."""
        return jsonify({"camera": config.camera, "stream_url": config.live_stream_url})

    @app.get("/live.jpg")
    def live_snapshot() -> Response:
        """A still from Frigate, shown by the Live Feed page while the moving picture is unavailable."""
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
