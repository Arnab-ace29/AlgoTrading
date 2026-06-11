"""
SEC-02 regression: the OpenAlgo API key must be sent once (JSON body only) and
never persisted into OrderResult.raw_response.

Before: the key was sent in BOTH an `x-api-key` header and the `apikey` body
field, and paper-mode orders returned `raw_response=payload` (which embedded the
key in the object callers/logs see).

    .venv/bin/python scripts/test_openalgo_security.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live.openalgo_client import OpenAlgoClient, _redact

PASS, FAIL = 0, 0
SECRET = "SUPER_SECRET_KEY_123"


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {msg}")
    else:
        FAIL += 1; print(f"  ✗ FAIL: {msg}")


def main() -> int:
    print("=" * 60); print("SEC-02 — API key not duplicated / not persisted"); print("=" * 60)

    client = OpenAlgoClient(api_key=SECRET, paper=True)

    # 1. Key is not in the request headers (sent in the body only).
    check(SECRET not in str(client._headers), "api key absent from request headers")
    check({k.lower() for k in client._headers} == {"content-type"},
          "headers are Content-Type only (no x-api-key)")

    # 2. A paper order must not return the secret in raw_response.
    r = client.place_order("RELIANCE", action="BUY", quantity=1)
    check(r.success, "paper order succeeds")
    check(SECRET not in str(r.raw_response), "api key NOT stored in raw_response")
    check(r.raw_response.get("apikey") == "***REDACTED***", "apikey field is redacted in raw_response")
    check(r.raw_response.get("symbol") == "RELIANCE", "non-secret payload fields are preserved")

    # 3. _redact unit behaviour.
    red = _redact({"apikey": SECRET, "access_token": "TOKENVAL_ZZZ", "symbol": "X", "quantity": "1"})
    check(SECRET not in str(red) and "TOKENVAL_ZZZ" not in str(red), "_redact removes all secret values")
    check(red["apikey"] == "***REDACTED***" and red["access_token"] == "***REDACTED***",
          "_redact masks every sensitive key")
    check(red["symbol"] == "X" and red["quantity"] == "1", "_redact keeps non-secret fields")
    check(_redact("not-a-dict") == "not-a-dict", "_redact passes through non-dicts safely")

    # 4. The client still HOLDS the key in memory so it can authenticate in the
    #    body of real requests — it's just never duplicated or persisted.
    check(client.api_key == SECRET, "client retains the key for body auth")

    print("=" * 60); print(f"PASS={PASS}  FAIL={FAIL}"); print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
