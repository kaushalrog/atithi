"""go_live.py — one command puts VoxAgent on the phone network.

    run.bat phone        (or:  .venv\\Scripts\\python go_live.py)

What it does, in order:
  1. Checks your Twilio credentials in .env
  2. Downloads cloudflared once (~40 MB, free, no account) and opens a public
     tunnel to this machine — Twilio can now reach your laptop
  3. Saves the tunnel URL into .env (PUBLIC_BASE_URL)
  4. Points your Twilio number's incoming-call webhook at the tunnel,
     through Twilio's API — nothing to click in their console
  5. Starts the VoxAgent server

Then just CALL YOUR TWILIO NUMBER. Leave the window open while testing;
Ctrl+C (or closing it) takes the phone line down again.

WHY a tunnel: Twilio lives on the internet and your laptop doesn't have a
public address. The tunnel is a temporary one (new URL each run — this script
re-points Twilio every time, so you never have to think about it). For a
permanent setup, host the server on a small cloud VM instead.
"""

import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
CLOUDFLARED = BASE_DIR / "cloudflared.exe"
CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/"
                   "download/cloudflared-windows-amd64.exe")
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

NGROK = BASE_DIR / "ngrok.exe"
NGROK_ZIP_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"

NETWORK_BLOCKED_HELP = """
  ⚠ This network seems to block Cloudflare tunnels (outbound port 7844).
    Two easy fixes — either works:
      a) Switch this laptop's Wi-Fi to your phone's hotspot and run again, OR
      b) Make a free account at https://ngrok.com (tunnels over normal
         HTTPS, almost never blocked), copy your authtoken from the
         dashboard, add this line to .env and run again:
             NGROK_AUTHTOKEN=your_token_here
"""


def ensure_cloudflared():
    if CLOUDFLARED.exists():
        return
    print("First run: downloading cloudflared (one time, ~40 MB)...")
    urllib.request.urlretrieve(CLOUDFLARED_URL, CLOUDFLARED)
    print("  done.")


def start_tunnel(port: int) -> tuple[subprocess.Popen, str]:
    """Start a quick tunnel and return (process, public https URL)."""
    proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    deadline = time.time() + 60
    url = None
    for line in proc.stdout:
        found = TUNNEL_URL_RE.search(line)
        if found:
            url = found.group(0)
            break
        if time.time() > deadline:
            break
    if url is None:
        proc.kill()
        raise RuntimeError("cloudflared did not produce a URL — check your internet connection.")
    # Keep draining cloudflared's output so its pipe never fills up and stalls it.
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return proc, url


def ensure_ngrok():
    if NGROK.exists():
        return
    print("First run: downloading ngrok (one time, ~10 MB)...")
    with urllib.request.urlopen(NGROK_ZIP_URL) as res:
        archive = zipfile.ZipFile(io.BytesIO(res.read()))
    archive.extract("ngrok.exe", BASE_DIR)
    print("  done.")


def start_ngrok(port: int, authtoken: str) -> tuple[subprocess.Popen, str]:
    """Start ngrok and read the public URL from its local API."""
    proc = subprocess.Popen(
        [str(NGROK), "http", str(port), "--authtoken", authtoken, "--log", "stdout"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            with urllib.request.urlopen(NGROK_API, timeout=3) as res:
                for t in json.load(res).get("tunnels", []):
                    if t.get("public_url", "").startswith("https://"):
                        return proc, t["public_url"]
        except Exception:
            pass
        time.sleep(1)
    proc.kill()
    raise RuntimeError("ngrok did not start — double-check NGROK_AUTHTOKEN in .env.")


def wait_until_reachable(url: str, timeout_s: int = 90):
    """Fresh tunnel hostnames take a few seconds to appear in DNS. Don't tell
    the founder to dial until Twilio would actually be able to reach us."""
    deadline = time.time() + timeout_s
    print("Waiting for the public URL to go live", end="", flush=True)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/", timeout=10) as res:
                if res.status == 200:
                    print(" — reachable!")
                    return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(3)
    raise RuntimeError("The tunnel URL never became reachable — try running again.")


def save_env_value(key: str, value: str):
    """Update KEY=... in .env (so the URL survives for other tools/restarts)."""
    path = BASE_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value  # the running server reads env at request time


def main():
    load_dotenv()
    port = int(os.getenv("PORT", "8765"))

    import telephony
    if not telephony.live_calls_enabled():
        # Going live exposes the whole server — portal, admin, phone line — to
        # the internet. That stays a deliberate, explicit step.
        print("Live calls are disabled. Read docs/SAFE_TESTING.md, then set")
        print("   ENABLE_LIVE_CALLS=true")
        print("in .env once its checklist passes.")
        sys.exit(1)

    import auth
    problem = auth.admin_password_problem()
    if problem:
        # The tunnel publishes /admin too; never with a weak or sample password.
        print(f"Not going live: {problem}.")
        sys.exit(1)

    missing = [k for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_NUMBER")
               if not os.getenv(k)]
    if missing:
        print("Almost there! Fill these in .env first (from console.twilio.com):")
        for k in missing:
            print(f"   {k}=")
        sys.exit(1)

    ngrok_token = os.getenv("NGROK_AUTHTOKEN", "").strip()
    if ngrok_token:
        ensure_ngrok()
        print("Opening the tunnel (ngrok)...")
        tunnel, url = start_ngrok(port, ngrok_token)
    else:
        ensure_cloudflared()
        print("Opening the tunnel (Cloudflare)...")
        tunnel, url = start_tunnel(port)
    save_env_value("PUBLIC_BASE_URL", url)
    print(f"  public URL: {url}")

    number = telephony.set_voice_webhook(url)
    print(f"  Twilio webhook updated for {number}")

    # The server isn't up yet, so probe the tunnel edge only after uvicorn
    # starts — do it from a background thread that then prints the banner.
    def announce():
        try:
            wait_until_reachable(url)
        except RuntimeError:
            print(NETWORK_BLOCKED_HELP if not ngrok_token else
                  "\n  ⚠ The tunnel never became reachable — try running again.")
            return
        print()
        print("=" * 58)
        print(f"  📞  VoxAgent is LIVE — call {number} now!")
        print("      (Trial accounts play a short Twilio message first —")
        print("       press any key when asked, then talk to your agent.)")
        print("      Ctrl+C here hangs up the phone line.")
        print("=" * 58)
        print()

    threading.Thread(target=announce, daemon=True).start()

    try:
        import uvicorn
        from server import app
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        tunnel.terminate()


if __name__ == "__main__":
    main()
