"""
Upstox Daily Token Refresh
Run this every morning before 9:00 IST to refresh the OAuth access token.
The token is stored back into .env automatically.

Usage:
    python scripts/refresh_token.py
    python scripts/refresh_token.py --totp YOUR_TOTP_SECRET  # for automated refresh
"""

from __future__ import annotations
import sys
import os
import argparse
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx
from loguru import logger
from dotenv import load_dotenv, set_key

load_dotenv()

MODE         = os.getenv("UPSTOX_MODE", "sandbox").lower()  # "sandbox" | "live"
SANDBOX      = (MODE == "sandbox")
BASE_URL     = "https://api.upstox.com"
ENV_FILE     = Path(__file__).parent.parent / ".env"

if MODE == "live":
    API_KEY      = os.getenv("LIVE_API_KEY", "")
    API_SECRET   = os.getenv("LIVE_API_SECRET", "")
    REDIRECT_URI = os.getenv("LIVE_REDIRECT_URI", "http://127.0.0.1")
    TOKEN_ENV_KEY = "LIVE_ACCESS_TOKEN"
else:
    API_KEY      = os.getenv("SANDBOX_API_KEY", "")
    API_SECRET   = os.getenv("SANDBOX_API_SECRET", "")
    REDIRECT_URI = os.getenv("SANDBOX_REDIRECT_URI", "http://127.0.0.1")
    TOKEN_ENV_KEY = "SANDBOX_ACCESS_TOKEN"


def get_auth_url() -> str:
    return (
        f"{BASE_URL}/v2/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={API_KEY}"
        f"&redirect_uri={REDIRECT_URI}"
    )


def exchange_code_for_token(auth_code: str) -> str:
    """Exchange the auth code for an access token."""
    resp = httpx.post(
        f"{BASE_URL}/v2/login/authorization/token",
        data={
            "code":          auth_code,
            "client_id":     API_KEY,
            "client_secret": API_SECRET,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        raise ValueError(f"No access_token in response: {data}")
    return token


def save_token_to_env(token: str) -> None:
    """Write access token back to .env under the correct mode key."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text("")
    set_key(str(ENV_FILE), TOKEN_ENV_KEY, token)
    logger.success(f"Token saved to .env as {TOKEN_ENV_KEY}")


def manual_flow() -> None:
    """Interactive OAuth flow — opens browser, user pastes redirect URL."""
    if not API_KEY or not API_SECRET:
        logger.error("UPSTOX_API_KEY and UPSTOX_API_SECRET must be set in .env")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Using these credentials — verify they match the portal EXACTLY:")
    print(f"  API_KEY ({MODE.upper():<8})  : {API_KEY}")
    print(f"  UPSTOX_REDIRECT_URI : {REDIRECT_URI}")
    print(f"  Mode (UPSTOX_MODE)  : {MODE.upper()}")
    print("=" * 60 + "\n")

    auth_url = get_auth_url()

    print("\n" + "=" * 60)
    print("STEP 1 — Open this URL in your browser and log in:")
    print()
    print(auth_url)
    print()
    print("=" * 60)

    # Try to open browser automatically
    try:
        opened = webbrowser.open(auth_url)
        if opened:
            print("(Browser opened automatically)")
        else:
            print("(Could not open browser — copy the URL above manually)")
    except Exception:
        print("(Could not open browser — copy the URL above manually)")

    print("\nSTEP 2 — After logging in, your browser will go to a blank")
    print(f"  page starting with:  {REDIRECT_URI}/?code=...")
    print("  Copy the FULL URL from the address bar and paste below.")
    print()
    print("Paste the redirect URL here:")
    redirect_url = input("> ").strip()

    # Extract auth code from URL
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    auth_code = params.get("code", [None])[0]

    if not auth_code:
        logger.error("Could not extract auth code from URL")
        sys.exit(1)

    logger.info("Exchanging auth code for access token...")
    token = exchange_code_for_token(auth_code)
    save_token_to_env(token)
    logger.success("Token refreshed successfully! You can now start the live runner.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh Upstox access token")
    parser.add_argument("--totp", type=str, help="TOTP secret for automated refresh (optional)")
    args = parser.parse_args()

    if SANDBOX:
        print("\n" + "=" * 60)
        print("UPSTOX_MODE=sandbox — Sandbox tokens are NOT generated via OAuth.")
        print()
        print("To get/refresh a sandbox token:")
        print("  1. Go to: https://account.upstox.com/developer/apps")
        print("  2. Find your Sandbox app → click 'Generate'")
        print("  3. Copy the token (valid 30 days)")
        print("  4. Paste it into .env as SANDBOX_ACCESS_TOKEN=<token>")
        print()
        print("To run the live OAuth flow instead:")
        print("  Change UPSTOX_MODE=live in .env, then re-run this script.")
        print("=" * 60 + "\n")
        sys.exit(0)

    manual_flow()
