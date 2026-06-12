# SEBI COMPLIANCE — Regulatory Requirements & Checklist

> SEBI's new algo trading framework (Feb 4, 2025 circular, NSE implementation May 2025).
> Fully active from 2026. This is not legal advice — verify with a SEBI-registered advisor.

---

## Summary of New Rules

SEBI has formalized algorithmic trading for retail investors under a structured framework:

- Every automated order via API must carry an **exchange-assigned Algo ID**
- Brokers (Upstox) are the compliance gatekeepers — algos run *through* your broker
- Two categories of algos with very different compliance paths:
  - **White-box** (visible logic) → easy registration
  - **Black-box** (hidden ML/LLM logic) → requires SEBI RA registration
- OpenAlgo is empanelled → using it as execution layer protects you

---

## Two Algo Categories

### White-Box Algos (Phase 1 — Rule-Based)
- Logic fully visible to user and broker
- Examples: VWAP breakout, RSI momentum, mean reversion (our Phase 1)
- Registration: through your broker (Upstox) → exchange fast-track approval
- No SEBI RA registration required
- **Our Phase 1 is white-box ✅**

### Black-Box Algos (Phase 2+ — ML/LLM)
- Logic hidden from user (ML model internals, LLM reasoning)
- Examples: XGBoost models, RL exit agent, LLM agents (our Phase 2–4)
- Registration: requires **SEBI Research Analyst (RA) registration**
- OR: trade only through an **empanelled vendor** (OpenAlgo qualifies)
- **OpenAlgo is empanelled → our ML/LLM signals can run through it without RA registration**

---

## Compliance Checklist

### Phase 1 (Rule-Based Core) — Do Before Going Live

- [ ] **Register your strategy with Upstox**
  - Contact Upstox developer support
  - Submit: strategy name, description, logic (readable pseudocode)
  - Upstox registers it with NSE/BSE → you get an Algo ID
  - Algo ID must be attached to every order placed by the strategy

- [ ] **Configure OpenAlgo as execution layer**
  - OpenAlgo is already empanelled — orders routed through it are compliant
  - Do NOT place orders directly via raw Upstox SDK in live trading
  - Always use `live/openalgo_client.py` → OpenAlgo → Upstox

- [ ] **API Security Stack** (required by SEBI)
  - OAuth-based authentication: ✅ Upstox SDK handles this
  - Two-Factor Authentication (2FA): enable in Upstox developer settings
  - Static IP whitelisting: add your home/server IP in Upstox API settings
  - Unique API key per strategy: generate separate API key for algo vs manual trading

- [ ] **Implement kill switch** in code
  - `risk/circuit_breaker.py` — halts new entries on daily loss limit
  - `POST /api/system/kill` in dashboard — cancels all orders, exits positions
  - SEBI requires brokers to maintain exchange-level kill switch — OpenAlgo handles this

- [ ] **Maintain audit trail**
  - `trade_log` in SQLite = compliance record
  - Every trade: timestamp, symbol, side, qty, price, strategy, Algo ID, order ID
  - Keep audit trail for minimum 5 years (SEBI records requirement)
  - Dashboard `/security` page shows full audit log

- [ ] **Order rate limits**
  - Retail threshold: register algo only if crossing a defined OPS (orders-per-second) limit
  - Our system: max ~5 orders/minute at peak = well below threshold
  - Still register proactively to be compliant

### Phase 2–3 (ML/News — Black-Box)

Two paths — choose one:

**Path A: Continue using OpenAlgo (recommended)**
- Since OpenAlgo is empanelled, our ML signals running through it are covered
- No separate SEBI RA registration needed
- Keep doing: OpenAlgo → Upstox for all order placement
- Document that ML models are internal to your algo, OpenAlgo is the registered algo vendor

**Path B: SEBI Research Analyst (RA) Registration**
- Required if you want to sell/share your strategy with others
- Or if you want to run ML signals completely independently
- Process: Apply to SEBI, pay fees (₹5,000 for individuals), pass exam (NISM Series-XV)
- Timeline: 3–6 months
- **Start this process during Phase 2, not Phase 4**

### Phase 4 (LLM Agents — Black-Box)

- Definitely black-box → RA registration recommended
- OR continue routing through OpenAlgo (empanelled vendor path)
- LLM agents that generate trade signals = "advisory algo" in SEBI's classification
- If signals are shared with others (even informally) → RA registration mandatory

---

## Upstox API Registration Steps

1. Log in to Upstox Developer Portal: https://developer.upstox.com
2. Create an app (if not already done)
3. Note your API Key and Secret
4. Enable 2FA on the account
5. Add static IP whitelist (your home IP)
6. Contact Upstox support to register your algo strategy
7. Get exchange Algo ID once approved

---

## OpenAlgo Empanelment

OpenAlgo (`github.com/marketcalls/openalgo`) is:
- Self-hosted on your machine
- Connected to your Upstox account via OAuth
- Registered as a trading platform with Indian exchanges
- All orders routed through it carry proper identifiers

**How it protects you:**
- Orders placed via OpenAlgo's REST API are tagged with OpenAlgo's exchange registration
- You don't need to separately register each strategy with the exchange
- OpenAlgo handles the broker ↔ exchange compliance layer
- Their empanelment covers both white-box and black-box algos (for personal trading)

---

## What SEBI Cannot Stop (Personal Trading)

For **personal trading** (trading your own capital, not managing others' money):
- You can run any algo — white-box or black-box
- As long as it goes through a registered broker (Upstox ✅) and empanelled platform (OpenAlgo ✅)
- No RA registration needed for personal algo trading in Phase 1–2

RA registration is needed if:
- You share signals with others
- You charge for strategy access
- You manage others' capital
- You publish performance claims publicly

---

## STT & Tax Compliance

### Securities Transaction Tax (STT)
| Segment | Transaction | Rate |
|---|---|---|
| Equity intraday (MIS) | Buy + Sell | 0.025% on sell side only |
| Equity delivery (CNC) | Buy | 0.1% |
| Equity delivery (CNC) | Sell | 0.1% |
| F&O — Futures | Sell | 0.01% |
| F&O — Options (exercise) | 0.125% of intrinsic value | |
| Currency derivatives | Not applicable | |

### Brokerage (Upstox API)
- Equity intraday: ₹0 (API trades are free on Upstox)
- F&O: ₹0 (API trades are free on Upstox)
- Note: Upstox zero-brokerage applies to API-based orders

### Other charges to model in backtest
- Exchange transaction charges: 0.00322% NSE, 0.00295% BSE
- SEBI charges: 0.0001%
- GST on brokerage: 18%
- Stamp duty: 0.003% on buy side (equity)
- IPFT: 0.0001%

**Combined realistic cost per trade (equity intraday): ~0.05% round trip**

### Income Tax on Trading
- Intraday equity: treated as **Business Income** (not capital gains)
- F&O: treated as **Business Income** regardless of holding period
- Maintain trade_log as trading records for ITR filing
- Recommend: separate current account for trading capital

---

## Record Keeping Requirements

SEBI and tax authorities require:
- Order logs: all placed orders with timestamps, prices, quantities
- Trade confirmation: executed trades with exchange confirmation numbers
- Strategy documentation: description of algo logic (needed for white-box registration)
- 5-year retention minimum

**Our system covers this automatically:**
- `trade_log` SQLite table: all trade details with OpenAlgo order IDs
- `daily_performance` table: daily summaries
- Audit log in dashboard `/security` page
- OpenAlgo also maintains its own order records independently

---

## SEBI Resources

| Resource | URL |
|---|---|
| SEBI Algo Trading Circular Feb 2025 | https://www.sebi.gov.in/legal/circulars/feb-2025/ |
| NSE Algo Registration Guidelines | https://www.nseindia.com |
| SEBI RA Registration | https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFii=yes&intmId=4 |
| AlgoBulls SEBI Rules Summary | https://algobulls.com/blog/industry-insights-and-updates/sebi-new-algotrading-regulations-for-retail-investors-2026 |
| Fyers SEBI Rules Guide | https://fyers.in/blog/sebi-algo-trading-rules-and-regulations-in-india/ |
| NISM Series XV (RA Exam) | https://www.nism.ac.in |
