"""
Check universe symbol lists against the live Upstox NSE master.
Identifies renamed/delisted symbols and prints a correction map.
Also patches universes.json with known symbol changes.
"""
import sys, json, gzip
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import httpx
from data.instruments import resolve_instrument_key

UNIVERSES_FILE = ROOT / "config" / "universes.json"

# Known symbol renames (old → new) based on NSE master
SYMBOL_RENAMES = {
    "LTIM":       "LTM",       # LTIMindtree → LTM Limited
    "ZOMATO":     "ETERNAL",   # Zomato → Eternal Ltd
    "TATAMOTORS": "TMCV",      # Tata Motors → TMCV (commercial vehicles entity)
}
# TATAMOTORS also split into TMPV — add TMPV as additional entry
SYMBOL_ADDITIONS = {
    "nifty100":     ["TMPV"],    # Tata Motors Passenger Vehicles
    "nifty_total":  [],          # nifty_total already has TMCV and TMPV
}

def check_and_patch():
    with open(UNIVERSES_FILE, encoding="utf-8") as f:
        universes = json.load(f)

    print("=== Checking nifty100 symbols against Upstox NSE master ===")
    n100 = universes["nifty100"]
    missing_key = []
    for sym in n100:
        k = resolve_instrument_key(sym)
        if not k:
            print(f"  NO KEY: {sym}")
            missing_key.append(sym)
    print(f"  Symbols with no instrument key: {len(missing_key)}")

    print("\n=== Patching universes.json with known renames ===")
    changes_made = False
    for list_name in ["nifty50", "nifty100", "nifty_total", "fo_eligible"]:
        lst = universes[list_name]
        new_lst = []
        for sym in lst:
            if sym in SYMBOL_RENAMES:
                new_sym = SYMBOL_RENAMES[sym]
                print(f"  [{list_name}] {sym} → {new_sym}")
                # Only add if not already present
                if new_sym not in lst and new_sym not in new_lst:
                    new_lst.append(new_sym)
                    changes_made = True
                else:
                    print(f"    (already in list, skipping)")
            else:
                new_lst.append(sym)
        universes[list_name] = new_lst

    # Add TMPV to nifty100 if TATAMOTORS was there and TMPV isn't
    if "TMCV" in universes["nifty100"] and "TMPV" not in universes["nifty100"]:
        universes["nifty100"].append("TMPV")
        print("  [nifty100] Added TMPV (Tata Motors Passenger Vehicles)")
        changes_made = True

    if changes_made:
        with open(UNIVERSES_FILE, "w", encoding="utf-8") as f:
            json.dump(universes, f, indent=2, ensure_ascii=False)
        print("\n  universes.json updated.")
    else:
        print("\n  No changes needed.")

    # Final count
    print(f"\n=== Final universe sizes ===")
    for k, v in universes.items():
        print(f"  {k}: {len(v)} symbols")

if __name__ == "__main__":
    check_and_patch()
