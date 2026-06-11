import { useState, useEffect, useMemo, useRef, Fragment } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Pause, Loader2, SkipBack, Clapperboard } from 'lucide-react'
import { api } from '../api'
import type { ReplayResult, ReplayEvent, ReplayTrade, ReplayUniverseRow } from '../api'
import { Panel, SectionTitle, EmptyState, Badge } from '../components'

/* ── helpers ─────────────────────────────────────────────────── */
const fmt = (n: number | null | undefined, d = 0) =>
  n == null ? '—' : `${n >= 0 ? '' : ''}${n.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })}`
const rupee = (n: number | null | undefined, d = 0) => (n == null ? '—' : `₹${fmt(n, d)}`)
const clock = (iso: string) => { try { return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }) } catch { return iso } }
const ms = (iso: string) => new Date(iso).getTime()

const STATUS_VARIANT: Record<string, 'green' | 'red' | 'blue' | 'yellow' | 'neutral'> = {
  IN_POSITION: 'green', TRADED: 'blue', ARMED: 'yellow', GATED: 'red', SIGNAL: 'yellow', SCANNING: 'neutral',
}
const EVENT_COLOR: Record<string, string> = {
  UNIVERSE_SET: 'var(--blue)', SESSION_OPEN: 'var(--text-muted)', ARMED: 'var(--yellow)',
  ENTRY: 'var(--green)', EXIT: 'var(--blue)', GATE_BLOCK: 'var(--red)', ENTRY_SKIPPED: 'var(--text-muted)',
  TRAIL_SL: 'var(--text-dim)', BREAKER_HALT: 'var(--red)', SESSION_CLOSE: 'var(--text-muted)', NO_DATA: 'var(--red)',
}

/* Derive the portfolio state as-of a point in time (for live-paced playback). */
function deriveAsOf(events: ReplayEvent[], trades: ReplayTrade[], tNow: number) {
  const statusBySymbol: Record<string, string> = {}
  const openSymbols = new Set<string>()
  let cumNet = 0
  let halted = false
  const fired: ReplayEvent[] = []
  for (const e of events) {
    if (ms(e.t) > tNow) break
    fired.push(e)
    const s = e.symbol
    switch (e.type) {
      case 'ARMED': statusBySymbol[s] = 'ARMED'; break
      case 'GATE_BLOCK': statusBySymbol[s] = 'GATED'; break
      case 'ENTRY_SKIPPED': statusBySymbol[s] = 'ARMED'; break
      case 'ENTRY': statusBySymbol[s] = 'IN_POSITION'; openSymbols.add(s); break
      case 'EXIT': statusBySymbol[s] = 'TRADED'; openSymbols.delete(s)
        cumNet += (e.detail?.net as number) ?? 0; break
      case 'BREAKER_HALT': halted = true; break
    }
  }
  return { statusBySymbol, openSymbols, cumNet, halted, fired }
}

/* ── KPI tile ────────────────────────────────────────────────── */
function Kpi({ label, value, color, sub, glow }: { label: string; value: string; color?: string; sub?: string; glow?: boolean }) {
  return (
    <div className="t-panel" style={{ padding: '10px 13px', minWidth: 0 }}>
      <div className="t-label" style={{ marginBottom: 5 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: color ?? 'var(--text)', lineHeight: 1, textShadow: glow && color ? `0 0 12px ${color}55` : undefined, fontFamily: 'monospace' }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="t-label" style={{ marginBottom: 5 }}>{children}</div>
}

/* ── main page ───────────────────────────────────────────────── */
export default function ActionReplay() {
  const qc = useQueryClient()
  const [form, setForm] = useState(() => ({
    date: new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10),
    risk_profile: 'LOW' as 'LOW' | 'MEDIUM' | 'HIGH',
    capital: 100000,
    use_ml_gates: true,
    use_margin: false,
  }))

  const { data: status } = useQuery({ queryKey: ['replay-status'], queryFn: api.replayStatus, refetchInterval: 800 })
  const running = status?.state === 'running'

  const { data: resultRaw } = useQuery({
    queryKey: ['replay-result'], queryFn: api.replayResult,
    refetchInterval: running ? 1500 : false,
  })
  const result = resultRaw && 'run_id' in resultRaw ? (resultRaw as ReplayResult) : null

  const runMut = useMutation({
    mutationFn: api.runReplay,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['replay-status'] }) },
  })

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle>Action Replay — relive a trading day, bar by bar</SectionTitle>

      {/* Config bar */}
      <Panel title="Setup" accent="var(--blue)">
        <div style={{ display: 'flex', gap: 18, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div>
            <Label>Trading Day</Label>
            <input type="date" value={form.date} max={new Date().toISOString().slice(0, 10)}
              onChange={e => setForm(p => ({ ...p, date: e.target.value }))} />
          </div>
          <div>
            <Label>Risk Profile</Label>
            <div style={{ display: 'flex', gap: 4 }}>
              {(['LOW', 'MEDIUM', 'HIGH'] as const).map(r => (
                <button key={r} onClick={() => setForm(p => ({ ...p, risk_profile: r }))}
                  className={form.risk_profile === r ? 't-btn t-btn-blue' : 't-btn'}>{r}</button>
              ))}
            </div>
          </div>
          <div>
            <Label>Capital (₹)</Label>
            <input type="number" value={form.capital} step={10000} min={10000} style={{ width: 110 }}
              onChange={e => setForm(p => ({ ...p, capital: Number(e.target.value) }))} />
          </div>
          <div>
            <Label>ML Gates</Label>
            <button onClick={() => setForm(p => ({ ...p, use_ml_gates: !p.use_ml_gates }))}
              className={form.use_ml_gates ? 't-btn t-btn-green' : 't-btn'}>
              {form.use_ml_gates ? 'ON (live-faithful)' : 'OFF (rules only)'}
            </button>
          </div>
          <div>
            <Label>MIS Margin</Label>
            <button onClick={() => setForm(p => ({ ...p, use_margin: !p.use_margin }))}
              className={form.use_margin ? 't-btn t-btn-yellow' : 't-btn'}
              title={form.use_margin
                ? 'Margin ON — position sizes scaled up by broker MIS multiplier (needs margin cache)'
                : 'Margin OFF — cash-only sizing (conservative)'}>
              {form.use_margin ? '⚡ MIS ON' : 'CASH ONLY'}
            </button>
          </div>
          <button onClick={() => runMut.mutate(form)} disabled={running}
            className="t-btn t-btn-green" style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 16px' }}>
            {running ? <><Loader2 size={13} style={{ animation: 'spin 0.7s linear infinite' }} /> Replaying…</> : <><Clapperboard size={13} /> Run Replay</>}
          </button>
        </div>
        {running && (
          <div style={{ marginTop: 12 }}>
            <div style={{ height: 4, background: 'var(--border)', overflow: 'hidden' }}>
              <div style={{ width: `${(status?.progress ?? 0) * 100}%`, height: '100%', background: 'var(--green)', transition: 'width 0.4s' }} />
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 5 }}>{status?.message}</div>
          </div>
        )}
        {status?.state === 'error' && (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--red)' }}>Error: {status.message}</div>
        )}
      </Panel>

      {result ? <ReplayView result={result} /> : (
        <Panel title="Result"><EmptyState msg="Pick a day and run a replay to relive it" /></Panel>
      )}
    </div>
  )
}

/* ── result view with playback ───────────────────────────────── */
function ReplayView({ result }: { result: ReplayResult }) {
  const events = result.events ?? []
  const trades = result.trades ?? []
  const [t0, t1] = useMemo(() => {
    if (!events.length) return [0, 1]
    return [ms(events[0].t), ms(events[events.length - 1].t)]
  }, [events])

  // playback: frac 0..1 over the session; 1 = full day shown.
  const [frac, setFrac] = useState(1)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(20)            // session-minutes per real-second
  const raf = useRef<number | null>(null)
  const last = useRef<number>(0)

  // reset to full view whenever a new result arrives
  useEffect(() => { setFrac(1); setPlaying(false) }, [result.run_id])

  useEffect(() => {
    if (!playing) { if (raf.current) cancelAnimationFrame(raf.current); return }
    const span = Math.max(1, t1 - t0)
    const tick = (now: number) => {
      if (!last.current) last.current = now
      const dt = (now - last.current) / 1000
      last.current = now
      setFrac(f => {
        const next = f + (speed * 60000 * dt) / span
        if (next >= 1) { setPlaying(false); return 1 }
        return next
      })
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => { if (raf.current) cancelAnimationFrame(raf.current); last.current = 0 }
  }, [playing, speed, t0, t1])

  const tNow = t0 + (t1 - t0) * frac
  const asOf = useMemo(() => deriveAsOf(events, trades, tNow), [events, trades, tNow])
  const isLive = frac < 1

  const s = result.summary
  // PnL shown: as-of playhead when scrubbing, else the final summary net.
  const shownNet = isLive ? asOf.cumNet : s.net_pnl
  const costParts = s.cost_parts ?? {}

  const startPlay = () => { if (frac >= 1) setFrac(0); last.current = 0; setPlaying(true) }

  const noData = events.find(e => e.type === 'NO_DATA')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {noData && (
        <div style={{ padding: '10px 14px', border: '1px solid #4a1a1a', background: 'var(--red-dim)', color: 'var(--red)', fontSize: 12 }}>
          <b>No data for this day.</b> {String(noData.detail?.note ?? '')}
        </div>
      )}
      {/* PnL strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10 }}>
        <Kpi label={isLive ? 'Net P&L (so far)' : 'Net P&L'} value={rupee(shownNet)} glow
          color={shownNet >= 0 ? 'var(--green)' : 'var(--red)'} sub={`${result.date} · ${result.params.risk_profile}`} />
        <Kpi label="Gross P&L" value={rupee(s.gross_pnl)} color={s.gross_pnl >= 0 ? 'var(--green)' : 'var(--red)'} />
        <Kpi label="Total Costs" value={rupee(s.costs)} color="var(--yellow)"
          sub={`STT ${rupee(costParts.stt)} · Brk ${rupee(costParts.brokerage)} · Slp ${rupee(costParts.slippage)}`} />
        <Kpi label="Win Rate" value={`${s.win_rate}%`} color={s.win_rate >= 50 ? 'var(--green)' : 'var(--red)'}
          sub={`${s.wins}W / ${s.losses}L`} />
        <Kpi label="Trades" value={String(s.total_trades)}
          sub={`${s.longs ?? 0}L / ${s.shorts ?? 0}S · PF ${s.profit_factor ?? '—'}`} />
        <Kpi label="Margin / Exposure"
          value={s.uses_margin ? `${s.peak_leverage ?? 0}× MARGIN` : 'CASH ONLY'}
          color={s.uses_margin ? 'var(--yellow)' : 'var(--green)'}
          sub={`Peak ${rupee(s.peak_exposure)} (${s.peak_exposure_pct ?? 0}% of cap)`} />
      </div>

      {/* Universe + Trades */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, alignItems: 'start' }}>
        <UniverseTable rows={result.universe} asOf={asOf} isLive={isLive} />
        <TradesTable trades={trades} asOf={asOf} isLive={isLive} />
      </div>

      {/* Why no trade */}
      {Object.keys(result.gate_counts ?? {}).length > 0 && (
        <Panel title="Why no trade? — gate rejections" accent="var(--red)">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(result.gate_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <span key={k} style={{ fontSize: 10, padding: '4px 9px', background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text-dim)' }}>
                <b style={{ color: 'var(--red)' }}>{v}</b> &nbsp;{k}
              </span>
            ))}
          </div>
        </Panel>
      )}

      {/* Timeline + playback */}
      <Timeline events={events} t0={t0} t1={t1} frac={frac} setFrac={(f) => { setPlaying(false); setFrac(f) }}
        playing={playing} startPlay={startPlay} pause={() => setPlaying(false)}
        reset={() => { setPlaying(false); setFrac(0) }} speed={speed} setSpeed={setSpeed}
        tNow={tNow} fired={asOf.fired} />
    </div>
  )
}

/* ── universe table (with "Looking for position" status) ─────── */
function UniverseTable({ rows, asOf, isLive }: { rows: ReplayUniverseRow[]; asOf: ReturnType<typeof deriveAsOf>; isLive: boolean }) {
  return (
    <Panel title="Watchlist — universe & position scan" accent="var(--blue)"
      right={<span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{rows.length} symbols</span>}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Symbol', 'Strategies', 'Screener', 'Live Score', 'Regime', 'MIS Mult.', 'Looking for position'].map(h => (
                <th key={h} style={{ padding: '5px 8px 5px 0', textAlign: 'left', fontSize: 9, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const st = isLive ? (asOf.statusBySymbol[r.symbol] ?? 'SCANNING') : r.status
              return (
                <tr key={r.symbol} style={{ borderBottom: '1px solid var(--border)' }}
                  title={r.reasons?.join(' · ')}>
                  <td style={{ padding: '6px 8px 6px 0', fontWeight: 700, color: 'var(--text)' }}>{r.symbol}</td>
                  <td style={{ padding: '6px 8px 6px 0', color: 'var(--text-muted)', fontSize: 10 }}>{r.strategies.join(', ') || '—'}</td>
                  <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', color: 'var(--text-dim)' }}>{r.screener_score?.toFixed(3) ?? '—'}</td>
                  <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', color: (r.last_score ?? 0) > 0.05 ? 'var(--green)' : (r.last_score ?? 0) < -0.05 ? 'var(--red)' : 'var(--text-dim)' }}>
                    {r.last_score == null ? '—' : `${r.last_score > 0 ? '+' : ''}${r.last_score.toFixed(3)}`}
                  </td>
                  <td style={{ padding: '6px 8px 6px 0', color: 'var(--text-muted)', fontSize: 10 }}>{r.regime ?? '—'}</td>
                  <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', fontSize: 10,
                    color: r.multiplier == null ? 'var(--text-muted)'
                      : r.multiplier >= 4 ? 'var(--green)' : r.multiplier >= 2 ? 'var(--yellow)' : 'var(--red)',
                    title: r.margin_pct != null ? `Margin required: ${r.margin_pct}% of notional` : 'Run scripts/fetch_margin_multipliers.py to populate' }}
                  >{r.multiplier != null ? `${r.multiplier.toFixed(1)}×` : '—'}</td>
                  <td style={{ padding: '6px 0' }}><Badge text={st.replace('_', ' ')} variant={STATUS_VARIANT[st] ?? 'neutral'} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/* ── trades table ────────────────────────────────────────────── */
function TradesTable({ trades, asOf, isLive }: { trades: ReplayTrade[]; asOf: ReturnType<typeof deriveAsOf>; isLive: boolean }) {
  const [open, setOpen] = useState<number | null>(null)
  // when scrubbing, only show trades that have already exited by the playhead
  const shown = isLive ? trades.filter(t => asOf.fired.some(e => e.type === 'EXIT' && e.symbol === t.symbol && e.t === t.exit_time)) : trades
  return (
    <Panel title="Trades taken" accent="var(--green)"
      right={<span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{shown.length}{isLive ? ` / ${trades.length}` : ''}</span>}>
      {shown.length === 0 ? <EmptyState msg={isLive ? 'No trades yet at this point' : 'No trades this day'} /> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Time', 'Symbol', 'Dir', 'Qty', 'Entry', 'Exit', 'Notional', 'Net', 'Reason'].map(h => (
                  <th key={h} style={{ padding: '5px 8px 5px 0', textAlign: 'left', fontSize: 9, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((t, i) => (
                <Fragment key={i}>
                  <tr onClick={() => setOpen(open === i ? null : i)}
                    style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                    <td style={{ padding: '6px 8px 6px 0', color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 10 }}>{clock(t.entry_time)}→{clock(t.exit_time)}</td>
                    <td style={{ padding: '6px 8px 6px 0', fontWeight: 700, color: 'var(--text)' }}>{t.symbol}</td>
                    <td style={{ padding: '6px 8px 6px 0' }}><Badge text={t.direction || (t.side === 'BUY' ? 'LONG' : 'SHORT')} variant={(t.direction || t.side) === 'LONG' || t.side === 'BUY' ? 'green' : 'red'} /></td>
                    <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', color: 'var(--text-dim)' }}>{t.qty}</td>
                    <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', color: 'var(--text-dim)' }}>{t.entry_price}</td>
                    <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', color: 'var(--text-dim)' }}>{t.exit_price}</td>
                    <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', color: 'var(--text-dim)' }} title={`${t.leverage}× capital`}>{rupee(t.notional)}</td>
                    <td style={{ padding: '6px 8px 6px 0', fontFamily: 'monospace', fontWeight: 700, color: t.net_pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>{t.net_pnl >= 0 ? '+' : ''}{fmt(t.net_pnl, 0)}</td>
                    <td style={{ padding: '6px 0' }}><Badge text={t.exit_reason.replace('_', ' ')} variant={t.exit_reason.includes('TARGET') ? 'green' : t.exit_reason.includes('SL') ? 'red' : 'neutral'} /></td>
                  </tr>
                  {open === i && (
                    <tr style={{ background: 'var(--bg)' }}>
                      <td colSpan={9} style={{ padding: '8px 10px', fontSize: 10, color: 'var(--text-dim)' }}>
                        <div style={{ marginBottom: 4 }}><b style={{ color: 'var(--text-muted)' }}>Side:</b> {t.side} ({t.direction}) · <b style={{ color: 'var(--text-muted)' }}>Notional:</b> {rupee(t.notional)} = <b style={{ color: t.leverage > 1 ? 'var(--yellow)' : 'var(--green)' }}>{t.leverage}× capital</b> {t.leverage > 1 ? '(margin/leverage)' : '(within cash)'} · <b style={{ color: 'var(--text-muted)' }}>Held:</b> {t.bars_held} bars</div>
                        {t.margin_required != null && t.margin_required > 0 && (
                          <div style={{ marginBottom: 4 }}>
                            <b style={{ color: 'var(--text-muted)' }}>MIS Margin blocked:</b>{' '}
                            <span style={{ color: 'var(--yellow)', fontFamily: 'monospace' }}>{rupee(t.margin_required)}</span>
                            {' '}at{' '}
                            <span style={{ color: t.margin_multiplier != null && t.margin_multiplier >= 4 ? 'var(--green)' : 'var(--yellow)', fontFamily: 'monospace' }}>
                              {t.margin_multiplier?.toFixed(1)}× MIS leverage
                            </span>
                            {' '}({t.margin_multiplier != null ? (100 / t.margin_multiplier).toFixed(1) : '?'}% of notional)
                          </div>
                        )}
                        {(t.margin_required == null || t.margin_required === 0) && (
                          <div style={{ marginBottom: 4, color: 'var(--text-muted)', fontSize: 9 }}>
                            Margin data unavailable — run <code>scripts/fetch_margin_multipliers.py</code> with a live token
                          </div>
                        )}
                        <div style={{ marginBottom: 4 }}><b style={{ color: 'var(--text-muted)' }}>Entry score:</b> {t.entry_score} · <b style={{ color: 'var(--text-muted)' }}>Regime:</b> {t.regime} · <b style={{ color: 'var(--text-muted)' }}>Gross:</b> {fmt(t.gross_pnl, 0)} · <b style={{ color: 'var(--text-muted)' }}>Cost:</b> {fmt(t.cost, 1)}</div>
                        <div style={{ marginBottom: 4 }}><b style={{ color: 'var(--text-muted)' }}>Signals:</b> {Object.entries(t.signal_scores).map(([k, v]) => `${k}: ${v}`).join(' · ')}</div>
                        <div><b style={{ color: 'var(--text-muted)' }}>Sizing:</b> {t.sizing_note}</div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

/* ── timeline + playback controls ────────────────────────────── */
function Timeline({ events, t0, t1, frac, setFrac, playing, startPlay, pause, reset, speed, setSpeed, tNow, fired }: {
  events: ReplayEvent[]; t0: number; t1: number; frac: number; setFrac: (f: number) => void
  playing: boolean; startPlay: () => void; pause: () => void; reset: () => void
  speed: number; setSpeed: (n: number) => void; tNow: number; fired: ReplayEvent[]
}) {
  const span = Math.max(1, t1 - t0)
  // markers: entries/exits/halt/universe — skip the noisy per-bar ARMED/GATE for clarity
  const markers = events.filter(e => ['UNIVERSE_SET', 'ENTRY', 'EXIT', 'BREAKER_HALT', 'NO_DATA'].includes(e.type))
  const recent = [...fired].reverse().slice(0, 12)

  return (
    <Panel title="Session timeline — 09:15 → 15:30" accent="var(--green)"
      right={<span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--green)' }}>{new Date(tNow).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })}</span>}>
      {/* controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <button onClick={playing ? pause : startPlay} className="t-btn t-btn-green" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {playing ? <Pause size={12} /> : <Play size={12} />}{playing ? 'Pause' : 'Play'}
        </button>
        <button onClick={reset} className="t-btn" style={{ display: 'flex', alignItems: 'center', gap: 5 }}><SkipBack size={12} />Start</button>
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          {[5, 20, 60].map(sp => (
            <button key={sp} onClick={() => setSpeed(sp)} className={speed === sp ? 't-btn t-btn-blue' : 't-btn'}>{sp}×</button>
          ))}
          <button onClick={() => setFrac(1)} className="t-btn">Full day</button>
        </div>
      </div>

      {/* track */}
      <div style={{ position: 'relative', height: 46, marginBottom: 8 }}
        onClick={(e) => {
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
          setFrac(Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)))
        }}>
        <div style={{ position: 'absolute', top: 22, left: 0, right: 0, height: 2, background: 'var(--border)' }} />
        {/* progress fill */}
        <div style={{ position: 'absolute', top: 22, left: 0, width: `${frac * 100}%`, height: 2, background: 'var(--green)' }} />
        {/* markers */}
        {markers.map((e, i) => {
          const x = ((ms(e.t) - t0) / span) * 100
          const on = ms(e.t) <= tNow
          return (
            <div key={i} title={`${clock(e.t)} ${e.type} ${e.symbol}`} style={{
              position: 'absolute', top: e.type === 'ENTRY' ? 8 : 28, left: `calc(${x}% - 4px)`,
              width: 8, height: 8, borderRadius: e.type === 'BREAKER_HALT' ? 0 : '50%',
              background: on ? (EVENT_COLOR[e.type] ?? 'var(--text-dim)') : 'var(--border-hi)',
              border: '1px solid var(--bg)', transition: 'background 0.2s', cursor: 'pointer',
            }} />
          )
        })}
        {/* playhead */}
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: `calc(${frac * 100}% - 1px)`, width: 2, background: 'var(--green)', boxShadow: '0 0 8px var(--green)' }} />
      </div>

      {/* recent events log */}
      <div style={{ maxHeight: 150, overflowY: 'auto', fontFamily: 'monospace', fontSize: 10, border: '1px solid var(--border)', background: 'var(--bg)' }}>
        {recent.length === 0 ? (
          <div style={{ padding: '10px', color: 'var(--text-muted)' }}>Press Play to watch the day unfold…</div>
        ) : recent.map((e, i) => (
          <div key={i} style={{ padding: '3px 9px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8 }}>
            <span style={{ color: 'var(--text-muted)' }}>{clock(e.t)}</span>
            <span style={{ color: EVENT_COLOR[e.type] ?? 'var(--text-dim)', fontWeight: 700, minWidth: 96 }}>{e.type}</span>
            <span style={{ color: 'var(--text)' }}>{e.symbol}</span>
            <span style={{ color: 'var(--text-muted)' }}>{summarizeDetail(e)}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function summarizeDetail(e: ReplayEvent): string {
  const d = e.detail || {}
  switch (e.type) {
    case 'UNIVERSE_SET': return `${d.n ?? ''} symbols selected`
    case 'ENTRY': return `${d.direction ?? d.side} ${d.qty} @ ${d.price} · ${d.notional ? `₹${Number(d.notional).toLocaleString('en-IN')}` : ''} ${d.leverage ? `(${d.leverage}× cap)` : ''} ${d.margin_multiplier ? `[${d.margin_multiplier}× MIS]` : ''} score ${d.score}`
    case 'EXIT': return `${d.reason} @ ${d.exit_price} · net ${d.net}`
    case 'GATE_BLOCK': return String(d.reason ?? '')
    case 'ARMED': return `${d.side} armed (score ${d.score})`
    case 'BREAKER_HALT': return String(d.reason ?? '')
    case 'TRAIL_SL': return `SL → ${d.sl}`
    default: return ''
  }
}
