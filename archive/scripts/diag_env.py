"""Quick .env credential diagnostic — shows what's loaded without printing secrets."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

mode = os.getenv("UPSTOX_MODE", "sandbox").lower()
if mode == "live":
    key    = os.getenv("LIVE_API_KEY", "")
    secret = os.getenv("LIVE_API_SECRET", "")
    redir  = os.getenv("LIVE_REDIRECT_URI", "")
    token  = os.getenv("LIVE_ACCESS_TOKEN", "")
else:
    key    = os.getenv("SANDBOX_API_KEY", "")
    secret = os.getenv("SANDBOX_API_SECRET", "")
    redir  = os.getenv("SANDBOX_REDIRECT_URI", "")
    token  = os.getenv("SANDBOX_ACCESS_TOKEN", "")

PLACEHOLDERS = {"", "your_live_api_key_here", "your_sandbox_api_key_here",
                "your_live_api_secret_here", "your_sandbox_api_secret_here",
                "your_sandbox_access_token_here"}

def mask(v):
    if not v or v in PLACEHOLDERS:
        return "(EMPTY or placeholder)"
    return v[:4] + "..." + v[-4:]

print(f"UPSTOX_MODE   : {mode.upper()}")
print(f"API_KEY       : {mask(key)}")
print(f"API_SECRET    : {mask(secret)}")
print(f"REDIRECT_URI  : {redir or '(EMPTY)'}")
print(f"ACCESS_TOKEN  : {mask(token)}")
print()
if not key or key in PLACEHOLDERS:
    print("PROBLEM: API_KEY is missing — this causes UDAPI1013.")
    print(f"  Set {'LIVE_API_KEY' if mode=='live' else 'SANDBOX_API_KEY'} in .env")
elif not secret or secret in PLACEHOLDERS:
    print("PROBLEM: API_SECRET is missing.")
    print(f"  Set {'LIVE_API_SECRET' if mode=='live' else 'SANDBOX_API_SECRET'} in .env")
else:
    print("Credentials look set. If token exchange still fails, the key/secret may be wrong.")
