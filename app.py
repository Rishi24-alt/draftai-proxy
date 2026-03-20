import os
import json
import time
import urllib.request
from flask import Flask, request, Response, jsonify

app = Flask(_name_)
KEY  = os.environ.get("OPENAI_API_KEY", "")
BASE = "https://api.openai.com"

pending_jobs = {}
results      = {}
addin_status = {"online": False, "last_seen": 0}


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})


@app.route("/addin/register", methods=["POST"])
def addin_register():
    addin_status["online"]    = True
    addin_status["last_seen"] = time.time()
    return jsonify({"status": "registered"})


@app.route("/addin/status", methods=["GET"])
def addin_status_check():
    online = addin_status["online"] and (time.time() - addin_status["last_seen"]) < 30
    return jsonify({"online": online})


@app.route("/addin/job", methods=["GET"])
def addin_get_job():
    addin_status["online"]    = True
    addin_status["last_seen"] = time.time()
    if pending_jobs:
        session_id = next(iter(pending_jobs))
        job = pending_jobs.pop(session_id)
        return jsonify(job)
    return jsonify({"job": None, "session_id": None})


@app.route("/addin/job", methods=["POST"])
def addin_push_job():
    data       = request.get_json()
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "No session_id"}), 400
    pending_jobs[session_id] = data
    return jsonify({"status": "queued", "session_id": session_id})


@app.route("/addin/result", methods=["POST"])
def addin_push_result():
    data       = request.get_json()
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "No session_id"}), 400
    results[session_id] = data
    return jsonify({"status": "stored"})


@app.route("/addin/poll/<session_id>", methods=["GET"])
def addin_poll_result(session_id):
    if session_id in results:
        result = results.pop(session_id)
        return jsonify(result)
    return jsonify({"status": "waiting"})


@app.route("/analyze", methods=["POST"])
def analyze():
    return _proxy_to_openai("v1/chat/completions")


@app.route("/v1/<path:path>", methods=["GET", "POST", "DELETE", "PUT"])
def proxy_v1(path):
    return _proxy_to_openai(f"v1/{path}")


@app.route("/<path:path>", methods=["GET", "POST", "DELETE", "PUT"])
def proxy(path):
    if path.startswith("addin/"):
        return jsonify({"error": "Not found"}), 404
    return _proxy_to_openai(path)


def _proxy_to_openai(path):
    url  = f"{BASE}/{path}"
    body = request.get_data()
    try:
        req = urllib.request.Request(
            url,
            data=body if body else None,
            headers={
                "Content-Type":  request.content_type or "application/json",
                "Authorization": f"Bearer {KEY}",
            },
            method=request.method,
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            result       = r.read()
            content_type = r.headers.get("Content-Type", "application/json")
        return Response(result, content_type=content_type)
    except urllib.error.HTTPError as e:
        return Response(e.read(), status=e.code, content_type="application/json")
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


if _name_ == "_main_":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
