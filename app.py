import os
import json
import urllib.request
from flask import Flask, request, Response, jsonify

app   = Flask(__name__)
KEY   = os.environ.get("OPENAI_API_KEY", "")
BASE  = "https://api.openai.com"

# In-memory store for add-in results
# In production use Redis or a database
results_store = {}

@app.route("/ping", methods=["GET"])
def ping():
    return {"status": "ok"}

@app.route("/addin/push", methods=["POST"])
def addin_push():
    """Add-in POSTs its result here"""
    data = request.get_json()
    session_id = data.get("session_id", "default")
    results_store[session_id] = data
    return {"status": "received"}

@app.route("/addin/poll/<session_id>", methods=["GET"])
def addin_poll(session_id):
    """Streamlit polls this to get add-in result"""
    result = results_store.pop(session_id, None)
    if result:
        return jsonify(result)
    return jsonify({"status": "waiting"})

@app.route("/<path:path>", methods=["GET","POST","DELETE","PUT"])
def proxy(path):
    url  = f"{BASE}/{path}"
    body = request.get_data()
    req  = urllib.request.Request(
        url,
        data=body if body else None,
        headers={
            "Content-Type":    request.content_type or "application/json",
            "Authorization":   f"Bearer {KEY}",
        },
        method=request.method,
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        result = r.read()
        content_type = r.headers.get("Content-Type", "application/json")
    return Response(result, content_type=content_type)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
