"""
Grass Desktop App — Full Login Automation with OTP
===================================================
Flow:
  1. Launch Grass desktop app
  2. Click "Sign In"
  3. Type your Gmail address
  4. Click "Continue"
  5. Poll OTP server until code arrives
  6. Type OTP into the field
  7. Click "Sign In" / "Verify"
  8. Hand off to watchdog loop

Requirements:
    pip install pywinauto pywin32 psutil requests

Config:
    ① Set GRASS_EXE_PATH to your Grass.exe location
    ② Set GRASS_EMAIL to your Gmail address
    ③ Set OTP_SERVER_URL to your Render service URL
    ④ Set OTP_SECRET to match your Render env var
"""

import time
import subprocess
import os
import sys
import requests
import psutil

# ─────────────────────────────────────────────
# CONFIG — edit these
# ─────────────────────────────────────────────

GRASS_EXE_PATH  = r"C:\Users\YOUR_USER\AppData\Local\Programs\Grass\Grass.exe"
GRASS_EMAIL     = "your@gmail.com"

OTP_SERVER_URL  = "https://grass-otp-server.onrender.com"   # your Render URL
OTP_SECRET      = "changeme123"                              # match Render env var

OTP_POLL_INTERVAL = 3    # seconds between polls
OTP_TIMEOUT       = 120  # give up after 2 minutes

CHECK_INTERVAL    = 60   # watchdog check interval (seconds)

# ─────────────────────────────────────────────
# DEPENDENCY CHECK
# ─────────────────────────────────────────────

def check_deps():
    missing = []
    for pkg in ["pywinauto", "win32gui", "psutil", "requests"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[!] Install missing packages:\n    pip install pywinauto pywin32 psutil requests")
        sys.exit(1)

check_deps()

import win32gui
import win32con
from pywinauto import Application
from pywinauto.findwindows import ElementNotFoundError
from pywinauto.keyboard import send_keys

# ─────────────────────────────────────────────
# PROCESS HELPERS
# ─────────────────────────────────────────────

def find_grass_process():
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if "grass" in (proc.info['name'] or "").lower():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def launch_grass():
    if not os.path.exists(GRASS_EXE_PATH):
        print(f"[FATAL] Grass.exe not found: {GRASS_EXE_PATH}")
        sys.exit(1)
    print("[*] Launching Grass...")
    subprocess.Popen([GRASS_EXE_PATH])
    time.sleep(6)  # wait for window to appear


def ensure_grass_running():
    proc = find_grass_process()
    if proc:
        print(f"[OK] Grass already running (PID {proc.pid})")
        return proc
    launch_grass()
    proc = find_grass_process()
    if not proc:
        print("[FATAL] Failed to start Grass.")
        sys.exit(1)
    return proc

# ─────────────────────────────────────────────
# WINDOW / pywinauto HELPERS
# ─────────────────────────────────────────────

def connect_to_grass_window(retries=5):
    """Connect pywinauto to the Grass window."""
    for i in range(retries):
        try:
            app = Application(backend="uia").connect(title_re=".*[Gg]rass.*", timeout=5)
            win = app.top_window()
            print(f"[OK] Connected to window: '{win.window_text()}'")
            return app, win
        except ElementNotFoundError:
            print(f"[*] Waiting for window... ({i+1}/{retries})")
            time.sleep(3)
    print("[FATAL] Could not connect to Grass window.")
    sys.exit(1)


def find_control(win, title=None, control_type=None, auto_id=None):
    """Flexible control finder — tries multiple strategies."""
    kwargs = {}
    if title:        kwargs["title"]        = title
    if control_type: kwargs["control_type"] = control_type
    if auto_id:      kwargs["auto_id"]      = auto_id
    try:
        ctrl = win.child_window(**kwargs)
        ctrl.wait("visible", timeout=10)
        return ctrl
    except Exception:
        return None


def click_button(win, *titles):
    """Try a list of possible button titles until one works."""
    for title in titles:
        btn = find_control(win, title=title, control_type="Button")
        if btn:
            try:
                btn.click_input()
                print(f"    [CLICKED] '{title}'")
                return True
            except Exception:
                pass
    print(f"    [WARN] None of these buttons found: {titles}")
    return False


def type_into_field(win, value, field_title=None, control_type="Edit", placeholder=None):
    """
    Find an Edit/input field and type into it.
    Tries by title, then by placeholder, then by index.
    """
    ctrl = None

    if field_title:
        ctrl = find_control(win, title=field_title, control_type=control_type)

    if ctrl is None:
        # Fallback: grab all Edit controls and use the first visible one
        try:
            edits = win.children(control_type="Edit")
            if edits:
                ctrl = edits[0]
        except Exception:
            pass

    if ctrl is None:
        print(f"    [WARN] Could not find input field")
        return False

    try:
        ctrl.click_input()
        ctrl.type_keys("^a")          # select all
        ctrl.type_keys("{DELETE}")    # clear
        ctrl.type_keys(value, with_spaces=True)
        print(f"    [TYPED] '{value}'")
        return True
    except Exception as e:
        print(f"    [ERROR] typing failed: {e}")
        return False

# ─────────────────────────────────────────────
# OTP SERVER COMMUNICATION
# ─────────────────────────────────────────────

def poll_for_otp(timeout=OTP_TIMEOUT, interval=OTP_POLL_INTERVAL):
    """
    Poll the Render OTP server until a code arrives or timeout.
    Returns the OTP string, or None on timeout.
    """
    url = f"{OTP_SERVER_URL}/get-otp"
    params = {"secret": OTP_SECRET}
    deadline = time.time() + timeout

    print(f"[*] Polling OTP server (timeout={timeout}s)...")
    while time.time() < deadline:
        try:
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            status = data.get("status")

            if status == "ok":
                otp = data["otp"]
                print(f"[OK] OTP received from server: {otp}")
                return otp
            elif status == "waiting":
                print(f"    [WAIT] No OTP yet... retrying in {interval}s")
            elif status == "expired":
                print(f"    [WARN] OTP expired on server.")
                return None
            elif status == "already_used":
                print(f"    [WARN] OTP already used.")
                return None

        except requests.exceptions.ConnectionError:
            print(f"    [ERROR] Cannot reach OTP server: {OTP_SERVER_URL}")
        except Exception as e:
            print(f"    [ERROR] Poll failed: {e}")

        time.sleep(interval)

    print("[TIMEOUT] No OTP received within time limit.")
    return None

# ─────────────────────────────────────────────
# LOGIN FLOW
# ─────────────────────────────────────────────

def do_login(win):
    """
    Execute the full Grass login flow:
      Sign In → email → Continue → OTP → Verify
    """
    print("\n[*] Starting login flow...")
    time.sleep(1)

    # ── Step 1: Click "Sign In" ──────────────
    print("[1] Looking for Sign In button...")
    clicked = click_button(win,
        "Sign In", "Sign in", "signin", "Login", "Log In", "Get Started"
    )
    if not clicked:
        print("    [INFO] May already be on login screen — proceeding.")
    time.sleep(2)
    win = win.top_window() if hasattr(win, 'top_window') else win

    # ── Step 2: Enter email ──────────────────
    print(f"[2] Entering email: {GRASS_EMAIL}")
    type_into_field(win, GRASS_EMAIL, field_title="Email")
    time.sleep(1)

    # ── Step 3: Click Continue ───────────────
    print("[3] Clicking Continue...")
    click_button(win, "Continue", "Next", "Send OTP", "Send Code")
    time.sleep(3)

    # ── Step 4: Poll server for OTP ──────────
    print("[4] Requesting OTP from server...")
    otp = poll_for_otp()

    if not otp:
        print("[FAIL] No OTP received — login aborted.")
        return False

    # ── Step 5: Enter OTP ────────────────────
    print(f"[5] Entering OTP: {otp}")
    # OTP fields are often multiple single-digit boxes OR one combined field
    otp_entered = False

    # Try: single combined field
    otp_entered = type_into_field(win, otp, field_title="OTP")
    if not otp_entered:
        otp_entered = type_into_field(win, otp, field_title="Code")
    if not otp_entered:
        # Fallback: type into whatever Edit field is focused
        otp_entered = type_into_field(win, otp)

    if not otp_entered:
        # Last resort: use keyboard directly (field may already be focused)
        try:
            send_keys(otp)
            print(f"    [TYPED via keyboard] {otp}")
            otp_entered = True
        except Exception as e:
            print(f"    [ERROR] keyboard fallback failed: {e}")

    time.sleep(1)

    # ── Step 6: Click Verify / Sign In ───────
    print("[6] Submitting OTP...")
    click_button(win,
        "Verify", "Submit", "Sign In", "Sign in", "Confirm", "Continue"
    )
    time.sleep(4)

    print("[OK] Login flow complete — checking if logged in...")
    return True

# ─────────────────────────────────────────────
# NETWORK HEALTH CHECK
# ─────────────────────────────────────────────

def check_network_activity(proc):
    try:
        conns = proc.connections(kind='inet')
        active = [c for c in conns if c.status == psutil.CONN_ESTABLISHED and c.raddr]
        if active:
            print(f"[OK] Active connections: {len(active)}")
            for c in active[:3]:
                print(f"    → {c.raddr.ip}:{c.raddr.port}")
            return True
        print("[WARN] No active connections detected.")
        return False
    except Exception as e:
        print(f"[ERROR] Network check: {e}")
        return False

# ─────────────────────────────────────────────
# WATCHDOG LOOP
# ─────────────────────────────────────────────

def watchdog(app, win):
    print("\n[*] Entering watchdog loop...")
    login_done = False

    while True:
        proc = find_grass_process()

        if not proc:
            print("[!] Grass died — relaunching...")
            launch_grass()
            app, win = connect_to_grass_window()
            login_done = False

        if not login_done:
            success = do_login(win)
            if success:
                login_done = True
                time.sleep(5)
            else:
                print("[!] Login failed — retrying in 30s...")
                time.sleep(30)
            continue

        # Already logged in — just check network health
        proc = find_grass_process()
        if proc:
            active = check_network_activity(proc)
            if not active:
                print("[!] No network activity — restarting Grass...")
                proc.kill()
                time.sleep(3)
                launch_grass()
                app, win = connect_to_grass_window()
                login_done = False
        else:
            login_done = False

        time.sleep(CHECK_INTERVAL)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Grass Auto Login + OTP + Watchdog")
    print("=" * 55)
    print(f"  Email      : {GRASS_EMAIL}")
    print(f"  OTP Server : {OTP_SERVER_URL}")
    print(f"  Exe Path   : {GRASS_EXE_PATH}")
    print("=" * 55)

    # 1. Start Grass
    ensure_grass_running()

    # 2. Connect to window
    app, win = connect_to_grass_window()

    # 3. Watchdog manages login + keep-alive
    try:
        watchdog(app, win)
    except KeyboardInterrupt:
        print("\n[*] Stopped by user.")


if __name__ == "__main__":
    main()
