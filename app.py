"""
Grass OTP Server — Deploy on Render
=====================================
Receives OTP pushed from Gmail (via webhook or manual push),
exposes a simple API for the automation script to poll.

Endpoints:
  POST /push-otp        { "otp": "066806", "secret": "YOUR_SECRET" }
  GET  /get-otp?secret=YOUR_SECRET
  POST /clear-otp       { "secret": "YOUR_SECRET" }
  GET  /health

Deploy on Render:
  1. Push this folder to GitHub
  2. Create a new Web Service on render.com
  3. Build command : pip install -r requirements.txt
  4. Start command : gunicorn app:app
  5. Set env var   : OTP_SECRET=your_random_secret_here
"""

import os
import time
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# ── In-memory OTP store ──────────────────────
_store = {
    "otp": None,
    "received_at": None,
    "used": False,
}

SECRET = os.environ.get("OTP_SECRET", "changeme123")
OTP_TTL = 300  # OTP expires after 5 minutes


def verify_secret(data=None, args=None):
    secret = None
    if data:
        secret = data.get("secret")
    if args:
        secret = args.get("secret")
    return secret == SECRET


# ── Routes ───────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


@app.route("/push-otp", methods=["POST"])
def push_otp():
    """Receive and store a new OTP."""
    data = request.get_json(silent=True) or {}

    if not verify_secret(data=data):
        return jsonify({"error": "Unauthorized"}), 401

    otp = str(data.get("otp", "")).strip()
    if not otp or not otp.isdigit():
        return jsonify({"error": "Invalid OTP — must be digits only"}), 400

    _store["otp"] = otp
    _store["received_at"] = time.time()
    _store["used"] = False

    print(f"[OTP] Received: {otp}")
    return jsonify({"status": "ok", "otp": otp})


@app.route("/get-otp", methods=["GET"])
def get_otp():
    """
    Return stored OTP if valid and fresh.
    Automation script polls this endpoint.
    """
    if not verify_secret(args=request.args):
        return jsonify({"error": "Unauthorized"}), 401

    otp = _store["otp"]
    received_at = _store["received_at"]

    if otp is None:
        return jsonify({"status": "waiting", "otp": None})

    age = time.time() - received_at
    if age > OTP_TTL:
        _store["otp"] = None
        return jsonify({"status": "expired", "otp": None})

    if _store["used"]:
        return jsonify({"status": "already_used", "otp": None})

    # Mark as used so it can't be replayed
    _store["used"] = True

    return jsonify({
        "status": "ok",
        "otp": otp,
        "age_seconds": int(age),
    })


@app.route("/clear-otp", methods=["POST"])
def clear_otp():
    """Manually clear stored OTP."""
    data = request.get_json(silent=True) or {}
    if not verify_secret(data=data):
        return jsonify({"error": "Unauthorized"}), 401
    _store["otp"] = None
    _store["received_at"] = None
    _store["used"] = False
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
