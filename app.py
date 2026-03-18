import os
import json
import urllib.request
from flask import Flask, request, Response

app = Flask(__name__)

@app.route("/ping", methods=["GET"])
def ping():
    return {"status": "ok"}

@app.route("/analyze", methods=["POST"])
def analyze():
    key  = os.environ.get("OPENAI_API_KEY", "")
    body = request.get_data()
    req  = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        result = r.read()
    return Response(result, content_type="application/json")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)