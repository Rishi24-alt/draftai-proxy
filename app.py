import os
import time
import urllib.request
from flask import Flask, request, Response, jsonify

app  = Flask(__name__)
KEY  = os.environ.get("OPENAI_API_KEY", "")
BASE = "https://api.openai.com"

# ─────────────────────────────────────────────────────────────
# Session-based routing stores
#
# addin_instances  : addin_id -> { last_seen, busy }
# user_addin_map   : user_session_id -> addin_id
# pending_jobs     : addin_id -> job dict  (one job per add-in)
# results          : user_session_id -> result dict
# ─────────────────────────────────────────────────────────────
addin_instances = {}   # addin_id -> {last_seen, busy}
user_addin_map  = {}   # user_session_id -> addin_id
pending_jobs    = {}   # addin_id -> job
results         = {}   # user_session_id -> result


def _addin_online(addin_id):
    """Check if a specific add-in is still alive (heartbeat < 15s)."""
    a = addin_instances.get(addin_id)
    return a is not None and (time.time() - a["last_seen"]) < 15


def _any_addin_online():
    """Check if at least one add-in is online."""
    return any(_addin_online(aid) for aid in addin_instances)


def _available_addin():
    """Return first non-busy online add-in ID, or None."""
    for aid, info in addin_instances.items():
        if _addin_online(aid) and not info.get("busy"):
            return aid
    return None


# ─────────────────────────────────────────────────────────────
# Basic
# ─────────────────────────────────────────────────────────────

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"})


# ─────────────────────────────────────────────────────────────
# Add-in endpoints (called by DraftAIAddin.cs)
# ─────────────────────────────────────────────────────────────

@app.route("/addin/register", methods=["POST"])
def addin_register():
    """Add-in registers on startup with its unique ID."""
    data     = request.get_json() or {}
    addin_id = data.get("addin_id")
    if not addin_id:
        return jsonify({"error": "No addin_id"}), 400
    addin_instances[addin_id] = {"last_seen": time.time(), "busy": False}
    return jsonify({"status": "registered", "addin_id": addin_id})


@app.route("/addin/status", methods=["GET"])
def addin_status_check():
    """Website checks if any add-in is online."""
    return jsonify({"online": _any_addin_online()})


@app.route("/addin/job/<addin_id>", methods=["GET"])
def addin_get_job(addin_id):
    """Add-in polls for ITS OWN jobs only."""
    # Update heartbeat
    if addin_id in addin_instances:
        addin_instances[addin_id]["last_seen"] = time.time()
    else:
        addin_instances[addin_id] = {"last_seen": time.time(), "busy": False}

    job = pending_jobs.pop(addin_id, None)
    if job:
        addin_instances[addin_id]["busy"] = True
        return jsonify(job)
    return jsonify({"job": None, "session_id": None})


@app.route("/addin/result", methods=["POST"])
def addin_push_result():
    """Add-in pushes result back — marks itself as free."""
    data          = request.get_json() or {}
    session_id    = data.get("session_id")
    addin_id      = data.get("addin_id")
    if not session_id:
        return jsonify({"error": "No session_id"}), 400
    results[session_id] = data
    # Free up the add-in
    if addin_id and addin_id in addin_instances:
        addin_instances[addin_id]["busy"] = False
    return jsonify({"status": "stored"})


# ─────────────────────────────────────────────────────────────
# Website endpoints (called by cad_converter.py)
# ─────────────────────────────────────────────────────────────

@app.route("/addin/connect", methods=["POST"])
def user_connect():
    """
    User requests a dedicated add-in.
    If user_token provided, only connects to add-in registered with that token.
    """
    data         = request.get_json() or {}
    user_session = data.get("user_session")
    user_token   = data.get("user_token")  # optional — ties user to their own add-in

    if not user_session:
        return jsonify({"error": "No user_session"}), 400

    # If user already has an assigned add-in that's still online, reuse it
    existing = user_addin_map.get(user_session)
    if existing and _addin_online(existing):
        return jsonify({"addin_id": existing, "status": "reused"})

    # If user_token provided, find the matching add-in
    if user_token:
        for aid in addin_instances:
            if aid.startswith(user_token) and _addin_online(aid) and not addin_instances[aid].get("busy"):
                user_addin_map[user_session] = aid
                return jsonify({"addin_id": aid, "status": "assigned"})
        return jsonify({"addin_id": None, "status": "no_addin_available"})

    # No token — assign any available add-in
    addin_id = _available_addin()
    if not addin_id:
        return jsonify({"addin_id": None, "status": "no_addin_available"})

    user_addin_map[user_session] = addin_id
    return jsonify({"addin_id": addin_id, "status": "assigned"})


@app.route("/addin/job", methods=["POST"])
def addin_push_job():
    """Website pushes a job to a SPECIFIC add-in instance."""
    data       = request.get_json() or {}
    session_id = data.get("session_id")
    addin_id   = data.get("addin_id")
    if not session_id or not addin_id:
        return jsonify({"error": "Need session_id and addin_id"}), 400
    pending_jobs[addin_id] = data
    return jsonify({"status": "queued"})


@app.route("/addin/poll/<session_id>", methods=["GET"])
def addin_poll_result(session_id):
    """Website polls for its job result."""
    if session_id in results:
        result = results.pop(session_id)
        return jsonify(result)
    return jsonify({"status": "waiting"})


@app.route("/addin/alive/<addin_id>", methods=["GET"])
def addin_alive(addin_id):
    """Check if a specific add-in instance is still online."""
    online = addin_id in addin_instances and _addin_online(addin_id)
    return jsonify({"online": online})


# ─────────────────────────────────────────────────────────────
# OpenAI proxy
# ─────────────────────────────────────────────────────────────

@app.route("/analyze", methods=["POST"])
def analyze():
    return _proxy_to_openai("v1/chat/completions")


@app.route("/chat/completions", methods=["POST"])
def chat_completions_no_v1():
    """Handle requests missing the /v1 prefix."""
    return _proxy_to_openai("v1/chat/completions")


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
