"""Word Detection's web side: Enrolment, asked for by the Enrolment page through the Correlator.

It is started by the service and shares its Enrolment; it is not run on its own.
"""

from __future__ import annotations

import logging

from flask import Flask, Response, jsonify, request, send_file
from waitress import serve
from werkzeug.exceptions import HTTPException

from .enrolment import Enrolment, EnrolmentError
from .references import NotEnrolled

log = logging.getLogger(__name__)


def create_app(enrolment: Enrolment) -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/state")
    def state() -> Response:
        return _fresh(jsonify(enrolment.state()))

    @app.post("/start")
    def start() -> Response:
        return jsonify(enrolment.start())

    @app.post("/stop")
    def stop() -> Response:
        return jsonify(enrolment.stop())

    @app.post("/discard")
    def discard() -> Response:
        return jsonify(enrolment.discard())

    @app.get("/recording.wav")
    def recording() -> Response:
        return _fresh(send_file(enrolment.recording_path(), mimetype="audio/wav"))

    @app.get("/spans")
    def spans() -> Response:
        return _fresh(jsonify({"spans": enrolment.suggested_spans()}))

    @app.post("/save")
    def save() -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _problem(400, 'Send JSON such as {"spans": [{"start": 1.2, "end": 2.6, "word": "play"}]}.')
        return jsonify(enrolment.save(body.get("spans")))

    @app.get("/words")
    def words() -> Response:
        return _fresh(jsonify({"words": enrolment.words()}))

    @app.get("/words/<word>/<name>")
    def clip(word: str, name: str) -> Response:
        return _fresh(send_file(enrolment.clip_path(word, name), mimetype="audio/wav"))

    @app.delete("/words/<word>")
    def remove_word(word: str) -> Response:
        enrolment.remove(word)
        return jsonify({"words": enrolment.words()})

    @app.delete("/words/<word>/<name>")
    def remove_clip(word: str, name: str) -> Response:
        enrolment.remove(word, name)
        return jsonify({"words": enrolment.words()})

    @app.errorhandler(EnrolmentError)
    def cannot(error: EnrolmentError) -> Response:
        return _problem(409, _sentence(error))

    @app.errorhandler(NotEnrolled)
    def missing(error: NotEnrolled) -> Response:
        return _problem(404, _sentence(error))

    @app.errorhandler(OSError)
    def file_problem(error: OSError) -> Response:
        log.error("An Enrolment file could not be used: %s", error)
        return _problem(500, "A file could not be read or written. See Word Detection's log.")

    @app.errorhandler(HTTPException)
    def http_problem(error: HTTPException) -> Response:
        return _problem(error.code or 500, error.description or error.name)

    return app


def serve_forever(enrolment: Enrolment, port: int) -> None:
    """Serve until the process ends. Run on a thread of its own, beside the listening loop."""
    try:
        serve(create_app(enrolment), host="0.0.0.0", port=port, threads=4, ident=None)
    except OSError as error:
        log.error("Enrolment cannot be served on port %d: %s", port, error)


def _fresh(reply: Response) -> Response:
    """What is enrolled changes under the same address, so nothing here may be kept by a browser."""
    reply.headers["Cache-Control"] = "no-store"
    return reply


def _sentence(error: Exception) -> str:
    message = str(error)
    return message[:1].upper() + message[1:] + "."


def _problem(status: int, message: str) -> Response:
    reply = jsonify({"error": message})
    reply.status_code = status
    return reply
