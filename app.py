"""
Grass OTP Server — Render Deploy
=================================
Endpoints:
  GET  /health
  POST /push-otp   { "otp": "123456", "secret": "..." }
  GET  /get-otp?secret=...
  POST /clear-otp  { "secret": "..." }
"""

import os
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

SECRET  = os.environ.get("OTP_SECRET", "changeme123")
OTP_TTL = 300  # 5 minutes

_store = {"otp": None, "received_at": None, "used": False}


def auth(data=None, args=None):
    s = (data or {}).get("secret") or (args or {}).get("secret")
    return s == SECRET


@app.route("/")
def index():
    return jsonify({"service": "grass-otp-server", "status": "running"})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/push-otp", methods=["POST"])
def push_otp():
    data = request.get_json(silent=True) or {}
    if not auth(data=data):
        return jsonify({"error": "Unauthorized"}), 401
    otp = str(data.get("otp", "")).strip()
    if not otp.isdigit():
        return jsonify({"error": "OTP must be digits"}), 400
    _store.update({"otp": otp, "received_at": time.time(), "used": False})
    print(f"[OTP] Stored: {otp}")
    return jsonify({"status": "ok", "otp": otp})


@app.route("/get-otp")
def get_otp():
    if not auth(args=request.args):
        return jsonify({"error": "Unauthorized"}), 401
    otp = _store["otp"]
    if otp is None:
        return jsonify({"status": "waiting", "otp": None})
    if time.time() - _store["received_at"] > OTP_TTL:
        _store["otp"] = None
        return jsonify({"status": "expired", "otp": None})
    if _store["used"]:
        return jsonify({"status": "already_used", "otp": None})
    _store["used"] = True
    return jsonify({"status": "ok", "otp": otp})


@app.route("/clear-otp", methods=["POST"])
def clear_otp():
    data = request.get_json(silent=True) or {}
    if not auth(data=data):
        return jsonify({"error": "Unauthorized"}), 401
    _store.update({"otp": None, "received_at": None, "used": False})
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
