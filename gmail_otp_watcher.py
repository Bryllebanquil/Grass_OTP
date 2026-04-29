"""
Gmail OTP Watcher — runs locally on your PC
=============================================
Watches your Gmail inbox for Grass OTP emails
and automatically pushes the code to your Render server.

Requirements:
    pip install google-auth google-auth-oauthlib google-api-python-client requests

Setup:
  1. Go to https://console.cloud.google.com
  2. Create project → Enable Gmail API
  3. Create OAuth2 credentials → Download as credentials.json
  4. Place credentials.json next to this script
  5. Run once — browser opens to authorize Gmail access
  6. After auth, token.json is saved for future runs
"""

import os
import re
import time
import base64
import requests
import json

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

OTP_SERVER_URL = "https://grass-otp-server.onrender.com"   # your Render URL
OTP_SECRET     = "changeme123"                              # match Render env var

POLL_INTERVAL  = 5    # check Gmail every 5 seconds
SENDER_FILTER  = "grassfoundation.io"  # only parse emails from this domain

# ─────────────────────────────────────────────
# GMAIL AUTH
# ─────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def get_gmail_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

# ─────────────────────────────────────────────
# EMAIL PARSING
# ─────────────────────────────────────────────

def extract_otp_from_text(text):
    """Find 6-digit OTP in email body."""
    match = re.search(r"\b(\d{6})\b", text)
    return match.group(1) if match else None


def get_message_body(msg):
    """Extract plain text body from Gmail message."""
    payload = msg.get("payload", {})
    parts   = payload.get("parts", [])

    # Simple single-part email
    if not parts:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    # Multi-part — look for text/plain
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    return ""


def get_message_subject(msg):
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == "subject":
            return h["value"]
    return ""


def get_message_from(msg):
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h["name"].lower() == "from":
            return h["value"]
    return ""

# ─────────────────────────────────────────────
# OTP PUSH
# ─────────────────────────────────────────────

def push_otp_to_server(otp):
    url  = f"{OTP_SERVER_URL}/push-otp"
    data = {"otp": otp, "secret": OTP_SECRET}
    try:
        resp = requests.post(url, json=data, timeout=5)
        if resp.status_code == 200:
            print(f"[OK] OTP '{otp}' pushed to server.")
            return True
        else:
            print(f"[ERROR] Server returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Could not push OTP: {e}")
        return False

# ─────────────────────────────────────────────
# GMAIL WATCHER
# ─────────────────────────────────────────────

def watch_gmail():
    print("[*] Authenticating with Gmail...")
    service = get_gmail_service()
    print("[OK] Gmail connected. Watching for Grass OTP emails...")
    print(f"     Sender filter : *@{SENDER_FILTER}")
    print(f"     Poll interval : {POLL_INTERVAL}s\n")

    seen_ids = set()

    while True:
        try:
            # Search for recent unread emails from Grass
            query = f"from:{SENDER_FILTER} is:unread subject:password OR subject:OTP OR subject:code"
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=5
            ).execute()

            messages = results.get("messages", [])

            for m in messages:
                msg_id = m["id"]
                if msg_id in seen_ids:
                    continue

                seen_ids.add(msg_id)

                # Fetch full message
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full"
                ).execute()

                sender  = get_message_from(msg)
                subject = get_message_subject(msg)
                body    = get_message_body(msg)

                print(f"[EMAIL] From: {sender}")
                print(f"        Subject: {subject}")

                otp = extract_otp_from_text(subject + " " + body)

                if otp:
                    print(f"[OTP FOUND] {otp}")
                    push_otp_to_server(otp)
                else:
                    print("        No OTP found in this email.")

        except Exception as e:
            print(f"[ERROR] Gmail poll failed: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    watch_gmail()
