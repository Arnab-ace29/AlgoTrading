"""
Position Sizer
Converts an ensemble score into: lot size, stop-loss price, target price, trailing SL.

Four stacked layers:
  1. Score tier → conviction. For CASH EQUITY (lot_size == 1) the base size is
     RISK-BASED — shares = (per-trade risk budget × conviction) / stop-distance — so
     it scales with capital instead of trading 1–3 shares. For F&O (lot_size > 1) the
     tier is the lot count (1/2/3), capped by the profile.
  2. Portfolio heat   → reduce if total open risk is high
  3. Kelly multiplier → scale by rolling win rate (after 20 trades)
  4. RL sizing agent  → context-aware override (Phase 2+, after 500 episodes)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


from config.settings import (
    TRADING_CAPITAL,
    SCORE_TIER_TRADE, SCORE_TIER_2LOT, SCORE_TIER_3LOT,
)
from config.risk_profiles import ACTIVE, RiskProfile
from signals.base import Direction, Regime

# Assumed "average" edge. The Kelly layer maps this to a 1.0× lot multiplier, so a
# freshly-calibrated sizer with no realized edge yet neither scales up nor down.
# Realized edges better than this scale size up (toward the lot cap); worse edges
# scale down toward 0 (stand down). See PositionSizer._kelly_multiplier (SIZE-03).
KELLY_BASELINE_WIN = 0.55
KELLY_BASELINE_RR  = 1.5


@dataclass
class SizingResult:
    qty:         int       # number of lots / shares
    sl_price:    float     # stop-loss price
    target_price: float    # profit target price
    risk_amount: float     # capital at risk = abs(entry - sl) × qty
    risk_pct:    float     # risk_amount / TRADING_CAPITAL
    sizing_note: str = ""  # which layer dominated
    margin_multiplier: float = 1.0  # MIS leverage applied (1.0 = cash/no margin)

    def to_dict(self) -> dict:
        return {
            "qty":               self.qty,
            "sl_price":          round(self.sl_price, 2),
            "target_price":      round(self.target_price, 2),
            "risk_amount":       round(self.risk_amount, 2),
            "risk_pct":          round(self.risk_pct * 100, 3),
            "sizing_note":       self.sizing_note,
            "margin_multiplier": round(self.margin_multiplier, 2),
        }


class PositionSizer:
    """
    Computes position size and SL/target for a given signal score.

    Usage:
        sizer = PositionSizer()
        result = sizer.size(
            symbol="RELIANCE",
            direction=Direction.LONG,
            score=0.72,
            entry_price=2950.0,
            atr=28.5,
            open_positions_risk=[...],  # current per-position risk amounts
            regime=Regime.TRENDING_UP,  # used for the CHOPPY 1-lot stand-down
        )
    """

    def __init__(
        self,
        capital: float = TRADING_CAPITAL,
        lot_size: int = 1,       # share lot size (1 for equity, varies for F&O)
        kelly_win_rate: float = 0.55,    # rolling win rate, updated externally
        kelly_rr_ratio: float = 1.5,     # rolling reward:risk, updated externally
        profile: RiskProfile = None,     # active risk profile; defaults to config ACTIVE
    ):
        self.capital        = capital
        self.lot_size       = lot_size
        self.kelly_win_rate = kelly_win_rate
        self.kelly_rr_ratio = kelly_rr_ratio
        self._trade_count   = 0      # how many trades seen so far (activates Kelly)
        # Injected so risk profile can be switched at runtime (dashboard) without a
        # module-global swap; falls back to the env-selected ACTIVE profile.
        self.risk           = profile or ACTIVE

    @staticmethod
    def score_tier_lots(score: float) -> tuple[int, str]:
        """
        Documented score→lots band (docs/SIGNALS.md → Position Sizing), the single
        source of truth driven by `config.settings.SCORE_TIER_*`. Returns
        ``(desired_lots, note)`` BEFORE the risk-profile cap, CHOPPY override, heat,
        and Kelly are applied. ``0`` means *signal only — no trade*:

            <0.65      → 0 lots (signal only)
            0.65–0.70  → 1 lot
            0.70–0.75  → 2 lots
            ≥0.75      → 3 lots
        """
        a = abs(score)
        if a >= SCORE_TIER_3LOT:
            return 3, "3LOT(>=0.75)"
        if a >= SCORE_TIER_2LOT:
            return 2, "2LOT(0.70-0.75)"
        if a >= SCORE_TIER_TRADE:
            return 1, "1LOT(0.65-0.70)"
        return 0, "NO_TRADE(<0.65)"

    def size(
        self,
        symbol: str,
        direction: Direction,
        score: float,
        entry_price: float,
        atr: float,
        open_positions_risk: Optional[list[float]] = None,
        regime: Regime = Regime.UNKNOWN,
        margin_multiplier: float = 1.0,
    ) -> Optional[SizingResult]:
        """
        Compute position size.
        Returns None when the trade should be stood down — score below the trade
        band (signal only), the CHOPPY 1-lot stand-down, or portfolio heat too high.
        """
        if entry_price <= 0 or atr <= 0:
            return None

        # ── Layer 1: Score tier → conviction (docs/SIGNALS.md, via config.SCORE_TIER_*) ─
        # 0.55–0.65 signal only · 0.65–0.70 tier 1 (0 in CHOPPY) · 0.70–0.75 tier 2 ·
        # ≥0.75 tier 3. The tier is a CONVICTION level, not a literal share count.
        desired_lots, tier_note = self.score_tier_lots(score)
        if desired_lots == 0:
            return None   # below the trade band — signal only, no trade
        if desired_lots == 1 and regime == Regime.CHOPPY:
            return None   # marginal-conviction tier-1 stands down in CHOPPY

        sl_dist = atr * self.risk.sl_atr_multiplier
        if sl_dist <= 0:
            return None

        # Effective capital — scaled by MIS margin multiplier (capped at MAX_MIS_LEVERAGE)
        # for cash equity only; F&O lots already carry built-in leverage.
        eff_mult    = max(1.0, margin_multiplier) if self.lot_size == 1 else 1.0
        eff_capital = self.capital * eff_mult

        # ── Base position size ─────────────────────────────────────────────────
        if self.lot_size > 1:
            # F&O / derivatives: the tier IS the number of lots, capped by the
            # profile; one lot = lot_size contracts.
            base_lots = min(desired_lots, self.risk.lot_size_cap)
            base_qty  = base_lots * self.lot_size
            tier_note += f" | {base_lots} lot(s)"
        else:
            # CASH EQUITY: size to the per-trade RISK BUDGET (risk-based sizing),
            # scaled by the conviction tier (1/2/3 → 1/3, 2/3, full budget). When
            # margin is enabled the budget grows proportionally with effective capital.
            per_trade_budget = self._per_trade_risk_budget(eff_capital)
            conviction  = desired_lots / 3.0
            risk_budget = per_trade_budget * conviction
            base_qty = int(risk_budget / sl_dist)
            if base_qty < 1:
                base_qty = 1   # we've decided to trade — take at least 1 share
            # Hard notional cap: one trade cannot consume more than 1/3 of
            # effective capital, preventing a single position absorbing all margin.
            max_qty_notional = max(1, int(eff_capital / (3.0 * entry_price)))
            base_qty = min(base_qty, max_qty_notional)
            margin_tag = f" @{eff_mult:.1f}×MIS" if eff_mult > 1.0 else ""
            tier_note += f" | {base_qty} sh (risk ₹{risk_budget:.0f}{margin_tag})"

        # ── Layer 2: Portfolio heat check (in shares/contracts) ────────────────
        if open_positions_risk:
            current_heat = sum(open_positions_risk) / self.capital
            if current_heat >= self.risk.portfolio_heat_limit_pct / 100:
                return None   # over the heat limit — skip this trade entirely
            remaining_heat_budget = self.risk.portfolio_heat_limit_pct / 100 - current_heat
            if (sl_dist * base_qty) / self.capital > remaining_heat_budget:
                # Reduce toward the heat budget; allow 0 so heat can force a no-trade.
                base_qty = max(0, int(remaining_heat_budget * self.capital / sl_dist))
                tier_note += "+HEAT_REDUCED"
                if base_qty == 0:
                    return None

        # ── Layer 3: Kelly multiplier (active after 20 trades) ────────────────
        # Edge-normalized scaler centered on 1.0 (see _kelly_multiplier). Kelly may
        # legitimately scale to 0 in a cold streak; we honour that.
        kelly_multiplier = 1.0
        if self._trade_count >= 20:
            kelly_multiplier = max(0.0, min(1.5, self._kelly_multiplier()))  # 0 = stand down
            base_qty = max(0, int(round(base_qty * kelly_multiplier)))
            tier_note += f"+KELLY({kelly_multiplier:.2f})"
            if base_qty == 0:
                return None   # Kelly says the edge is gone — no trade

        qty = base_qty
        if qty <= 0:
            return None       # every de-risking layer points to no-trade

        # ── SL and Target ─────────────────────────────────────────────────────
        target_dist = atr * self.risk.target_atr_multiplier

        if direction == Direction.LONG:
            sl_price     = entry_price - sl_dist
            target_price = entry_price + target_dist
        else:
            sl_price     = entry_price + sl_dist
            target_price = entry_price - target_dist

        sl_price     = round(sl_price, 2)
        target_price = round(target_price, 2)

        risk_amount = abs(entry_price - sl_price) * qty
        risk_pct    = risk_amount / self.capital

        # Final safety check: don't risk more than daily_loss_limit / max_trades
        max_risk_per_trade = self._per_trade_risk_budget(eff_capital)
        if risk_amount > max_risk_per_trade:
            # Scale down qty to fit within per-trade risk limit
            qty = max(1, int(max_risk_per_trade / abs(entry_price - sl_price)))
            risk_amount = abs(entry_price - sl_price) * qty
            risk_pct    = risk_amount / self.capital
            tier_note  += "+RISK_SCALED"

        return SizingResult(
            qty=qty,
            sl_price=sl_price,
            target_price=target_price,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
            sizing_note=f"Tier:{tier_note} | qty:{qty}",
            margin_multiplier=eff_mult,
        )

    def compute_trailing_sl(
        self,
        direction: Direction,
        entry_price: float,
        current_price: float,
        current_sl: float,
        atr: float,
    ) -> float:
        """
        Compute updated trailing SL price.
        Returns the new SL (always moves in favour of the trade, never against).
        """
        activation_move = atr * self.risk.trailing_sl_activation
        lock_in_move    = atr * self.risk.trailing_sl_lock

        if direction == Direction.LONG:
            unrealized = current_price - entry_price
            if unrealized >= activation_move:
                new_sl = current_price - lock_in_move
                return max(current_sl, new_sl)    # only move SL up
        else:
            unrealized = entry_price - current_price
            if unrealized >= activation_move:
                new_sl = current_price + lock_in_move
                return min(current_sl, new_sl)    # only move SL down

        return current_sl

    def _per_trade_risk_budget(self, effective_capital: float | None = None) -> float:
        """
        Capital risked on a single full-conviction trade = daily-loss budget split
        across the day's max trades. When margin is enabled, pass effective_capital
        (= actual_capital × multiplier) to scale the budget up accordingly.
        """
        cap = effective_capital if effective_capital is not None else self.capital
        return (self.risk.max_daily_loss_pct / 100.0) * cap / max(1, self.risk.max_trades_per_day)

    def update_kelly_stats(self, win_rate: float, rr_ratio: float, trade_count: int) -> None:
        """
        Refresh the rolling edge used by the Kelly layer. Called by live/runner.py
        after each closed trade (and once at startup) — see SIZE-03. Until this is
        called the sizer runs on the assumed baseline edge and Kelly is a no-op.
        """
        self.kelly_win_rate = win_rate
        self.kelly_rr_ratio = rr_ratio
        self._trade_count   = trade_count

    @staticmethod
    def _quarter_kelly(p: float, b: float) -> float:
        """
        Quarter-Kelly fraction for win-prob p and reward:risk b (>= 0).
        Full Kelly = (b·p - q) / b with q = 1-p; we take a quarter for safety.
        """
        if b <= 0:
            return 0.0
        kelly = (b * p - (1.0 - p)) / b
        return max(0.0, kelly * 0.25)

    def _compute_kelly_fraction(self) -> float:
        """Quarter-Kelly fraction for the current rolling edge."""
        return self._quarter_kelly(self.kelly_win_rate, self.kelly_rr_ratio)

    def _kelly_multiplier(self) -> float:
        """
        Lot-size scaler from Kelly, centered on 1.0 at the assumed baseline edge
        (``KELLY_BASELINE_WIN`` / ``KELLY_BASELINE_RR``).

        We scale the score-tier lot count by *current edge ÷ baseline edge*, NOT by
        the raw quarter-Kelly fraction. A raw quarter-Kelly fraction is ~0.06–0.25
        even for a strong edge, so using it directly would round almost every trade
        to 0 lots once Kelly activates (the SIZE-03 second-order bug). Normalizing
        keeps the multiplier near 1.0 for an average edge, lets it rise toward the
        cap for a strong edge, and fall toward 0 (stand down) for a poor/negative one.
        """
        baseline = self._quarter_kelly(KELLY_BASELINE_WIN, KELLY_BASELINE_RR)
        if baseline <= 0:
            return 1.0
        return self._compute_kelly_fraction() / baseline
