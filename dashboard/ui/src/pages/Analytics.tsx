import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts'
import { api } from '../api'
import type { RMultiple } from '../api'
import { KpiCard, Panel, Badge, SectionTitle, EmptyState, Spinner, Tip } from '../components'
import { CHART_STYLE } from '../theme'

const RANGES = [
  { label: '1W', days: 7 }, { label: '1M', days: 30 },
  { label: '3M', days: 90 }, { label: 'ALL', days: 9999 },
]
const MODES = ['ALL', 'PAPER', 'LIVE'] as const

const fmt = (v: number | null | undefined, d = 0) =>
  v == null ? '—' : `${v >= 0 ? '' : ''}${v.toFixed(d)}`
const rupee = (v: number | null | undefined) => v == null ? '—' : `${v >= 0 ? '+' : ''}₹${v.toFixed(0)}`
const sign = (v: number | null | undefined) => (v ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'

export default function Analytics() {
  const [days, setDays] = useState(9999)
  const [mode, setMode] = useState<typeof MODES[number]>('ALL')
  const m = mode === 'ALL' ? undefined : mode

  const { data: s, isLoading } = useQuery({ queryKey: ['an-summary', days, mode], queryFn: () => api.analyticsSummary(days, m) })
  const { data: rmult } = useQuery({ queryKey: ['an-rmult', days, mode], queryFn: () => api.rMultiples(days, m) })
  const { data: exits } = useQuery({ queryKey: ['an-exits', days, mode], queryFn: () => api.byExitReason(days, m) })

  // Edge verdict: gross edge must clear costs.
  const edgeOk = (s?.gross_bps ?? 0) > (s?.cost_bps ?? 0)

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle>
        Analytics & Simulation
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
          <RangeBtns value={days} onChange={setDays} />
          <ModeBtns value={mode} onChange={setMode} />
        </span>
      </SectionTitle>

      {/* ── Edge verdict banner (DASH-02): gross vs cost in bps of notional ── */}
      <Panel title="Edge vs Costs" accent={edgeOk ? 'var(--green)' : 'var(--red)'}
        right={<Badge text={edgeOk ? 'EDGE CLEARS COSTS' : 'NO EDGE — COSTS DOMINATE'} variant={edgeOk ? 'green' : 'red'} />}>
        {isLoading ? <Spinner /> : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
            <KpiCard label="Gross edge" value={`${fmt(s?.gross_bps, 2)} bps`} sub="of traded notional"
              color={sign(s?.gross_bps)} glow />
            <KpiCard label="Cost drag" value={`${fmt(s?.cost_bps, 2)} bps`} sub="round-trip costs" color="var(--red)" />
            <KpiCard label="Net P&L" value={rupee(s?.net_pnl)} sub={`gross ${rupee(s?.gross_pnl)} − costs ₹${(s?.costs ?? 0).toFixed(0)}`}
              color={sign(s?.net_pnl)} glow />
            <KpiCard label="Expectancy" value={rupee(s?.expectancy)} sub={`${s?.expectancy_R ?? '—'} R / trade`}
              color={sign(s?.expectancy)} />
          </div>
        )}
        {!isLoading && !edgeOk && (s?.trades ?? 0) > 0 && (
          <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            Gross edge ({fmt(s?.gross_bps, 2)} bps) does not clear round-trip costs ({fmt(s?.cost_bps, 2)} bps).
            The strategy is not yet profitable net of costs (KNOWN_ISSUES → BT-EDGE). Use the simulator below to test selectivity / cost assumptions.
          </div>
        )}
      </Panel>

      {/* ── Secondary KPI row ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <KpiCard label="Trades" value={String(s?.trades ?? 0)} sub={`${s?.wins ?? 0} W / ${s?.losses ?? 0} L`} />
        <KpiCard label="Win rate (net)" value={`${(s?.win_rate ?? 0).toFixed(1)}%`} color={(s?.win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--red)'} />
        <KpiCard label="Profit factor" value={s?.profit_factor == null ? '—' : s.profit_factor.toFixed(2)}
          color={(s?.profit_factor ?? 0) >= 1 ? 'var(--green)' : 'var(--red)'} sub="gross win ÷ gross loss" />
        <KpiCard label="Avg R" value={s?.avg_R == null ? '—' : s.avg_R.toFixed(2)} sub="net ÷ risk per trade" color={sign(s?.avg_R)} />
      </div>

      {/* ── R-multiple distribution (DASH-03) ── */}
      <Panel title="R-Multiple Distribution"
        right={<Tip text="Net P&L ÷ risk (|entry−SL|×qty) per trade. A profitable system has positive average R after costs."><span style={{ fontSize: 10, color: '#3d4155' }}>net ÷ risk · {(rmult ?? []).length} trades</span></Tip>}>
        <RHistogram data={rmult ?? []} />
      </Panel>

      {/* ── What-if simulator (DASH-04) ── */}
      <WhatIf days={days} mode={m} />

      {/* ── Exit-reason breakdown ── */}
      <Panel title="Net Performance by Exit Reason">
        {(exits ?? []).length === 0 ? <EmptyState msg="No closed trades in window" /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid #1a1d27' }}>
              {['Exit reason', 'Trades', 'Win rate', 'Net P&L', 'Avg net'].map(h => (
                <th key={h} style={{ padding: '6px 10px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {(exits ?? []).map(r => (
                <tr key={r.exit_reason} style={{ borderBottom: '1px solid #12141b' }}>
                  <td style={{ padding: '7px 10px 7px 0', fontWeight: 700, color: '#e2e4e9', fontSize: 12 }}>{r.exit_reason}</td>
                  <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)' }}>{r.trades}</td>
                  <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 11, color: r.win_rate >= 50 ? 'var(--green)' : 'var(--red)' }}>{r.win_rate?.toFixed(0)}%</td>
                  <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 11, color: sign(r.net_pnl) }}>{rupee(r.net_pnl)}</td>
                  <td style={{ padding: '7px 0', fontFamily: 'monospace', fontSize: 11, color: sign(r.avg_net) }}>{rupee(r.avg_net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {/* ── Data health (DASH-05) ── */}
      <DataHealthPanel />
    </div>
  )
}

/* ── R-multiple histogram ── */
function RHistogram({ data }: { data: RMultiple[] }) {
  const bins = useMemo(() => {
    const edges = [-Infinity, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3, Infinity]
    const labels = ['<-2', '-2', '-1.5', '-1', '-0.5', '0.5', '1', '1.5', '2', '3', '3+']
    const counts = new Array(labels.length).fill(0)
    for (const t of data) {
      for (let i = 0; i < labels.length; i++) {
        if (t.R >= edges[i] && t.R < edges[i + 1]) { counts[i]++; break }
      }
    }
    return labels.map((label, i) => ({ label, count: counts[i], neg: edges[i + 1] <= 0 }))
  }, [data])
  if (data.length === 0) return <EmptyState msg="No closed trades with a stop to compute R" />
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={bins} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid {...CHART_STYLE.grid} />
        <XAxis dataKey="label" {...CHART_STYLE.axis} />
        <YAxis {...CHART_STYLE.axis} allowDecimals={false} />
        <Tooltip {...CHART_STYLE.tooltip} formatter={(v) => [`${v} trades`, 'count']} />
        <Bar dataKey="count">
          {bins.map((b, i) => <Cell key={i} fill={b.neg ? 'var(--red)' : 'var(--green)'} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ── What-if simulator ── */
function WhatIf({ days, mode }: { days: number; mode?: string }) {
  const [costMult, setCostMult] = useState(1.0)
  const [minScore, setMinScore] = useState(0.0)
  const [onlyTargets, setOnlyTargets] = useState(false)
  const { data, isFetching } = useQuery({
    queryKey: ['whatif', days, mode, costMult, minScore, onlyTargets],
    queryFn: () => api.whatIf({ days, mode, cost_mult: costMult, min_score: minScore, only_target_exits: onlyTargets }),
  })
  const base = data?.baseline, sc = data?.scenario
  const delta = (sc?.net_pnl ?? 0) - (base?.net_pnl ?? 0)
  return (
    <Panel title="What-If Simulator"
      right={<Tip text="Re-prices the closed-trade log under different assumptions — no engine re-run. Test selectivity and cost sensitivity."><span style={{ fontSize: 10, color: '#3d4155' }}>{isFetching ? 'computing…' : `${data?.params.kept_trades ?? 0} kept / ${data?.params.dropped_trades ?? 0} dropped`}</span></Tip>}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        {/* Controls */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Slider label={`Cost multiplier · ${costMult.toFixed(2)}×`} min={0} max={2} step={0.1} value={costMult} onChange={setCostMult}
            hint="0.5× = if costs were halved (better broker / less slippage)" />
          <Slider label={`Min entry score · ${minScore.toFixed(2)}`} min={0} max={0.9} step={0.01} value={minScore} onChange={setMinScore}
            hint="Only keep trades whose conviction ≥ this (more selective)" />
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text-dim)', cursor: 'pointer' }}>
            <input type="checkbox" checked={onlyTargets} onChange={e => setOnlyTargets(e.target.checked)} />
            Only count target-hit exits (exit-discipline what-if)
          </label>
        </div>
        {/* Result */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, alignContent: 'start' }}>
          <Cmp label="Baseline net" v={rupee(base?.net_pnl)} color={sign(base?.net_pnl)} />
          <Cmp label="Scenario net" v={rupee(sc?.net_pnl)} color={sign(sc?.net_pnl)} sub={`${delta >= 0 ? '+' : ''}₹${delta.toFixed(0)} vs base`} />
          <Cmp label="Win rate" v={`${(sc?.win_rate ?? 0).toFixed(1)}%`} color={(sc?.win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--red)'} />
          <Cmp label="Expectancy" v={rupee(sc?.expectancy)} color={sign(sc?.expectancy)} sub={`gross ${fmt(sc?.gross_bps, 1)} bps vs cost ${fmt(sc?.cost_bps, 1)} bps`} />
        </div>
      </div>
    </Panel>
  )
}

function Slider({ label, min, max, step, value, onChange, hint }: {
  label: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void; hint?: string
}) {
  return (
    <div>
      <div className="t-label" style={{ marginBottom: 6 }}>{label}</div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: 'var(--green)' }} />
      {hint && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 4 }}>{hint}</div>}
    </div>
  )
}

function Cmp({ label, v, color, sub }: { label: string; v: string; color?: string; sub?: string }) {
  return (
    <div className="t-panel" style={{ padding: '10px 12px' }}>
      <div className="t-label" style={{ marginBottom: 5 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: color ?? 'var(--text)', lineHeight: 1 }}>{v}</div>
      {sub && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

/* ── Data health ── */
function DataHealthPanel() {
  const { data } = useQuery({ queryKey: ['an-health'], queryFn: api.dataHealth, refetchInterval: 30000 })
  const rows = data?.rows ?? []
  const anyDemo = rows.some(r => r.is_demo)
  return (
    <Panel title="Data Health & Coverage"
      accent={anyDemo ? 'var(--yellow)' : undefined}
      right={<span style={{ fontSize: 10, color: '#3d4155' }}>{data?.symbols ?? 0} symbols · {(data?.total_bars ?? 0).toLocaleString()} bars</span>}>
      {rows.length === 0 ? <EmptyState msg="No candle data — backfill before backtesting" /> : (
        <>
          {anyDemo && <div style={{ marginBottom: 8, fontSize: 10, color: 'var(--yellow)' }}>⚠ Some rows are DEMO/seed data — back-tests on these are not meaningful (backfill real data, DATA-01).</div>}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid #1a1d27' }}>
              {['Symbol', 'TF', 'Source', 'Bars', 'Last bar (age)', ''].map(h => (
                <th key={h} style={{ padding: '6px 10px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #12141b' }}>
                  <td style={{ padding: '6px 10px 6px 0', fontWeight: 700, color: '#e2e4e9', fontSize: 12 }}>{r.symbol}</td>
                  <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)' }}>{r.timeframe}</td>
                  <td style={{ padding: '6px 10px 6px 0', fontSize: 10, color: 'var(--text-muted)' }}>{r.source}</td>
                  <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)' }}>{r.bars.toLocaleString()}</td>
                  <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 10, color: (r.age_hours ?? 0) > 48 ? 'var(--yellow)' : 'var(--text-muted)' }}>
                    {r.age_hours == null ? '—' : r.age_hours < 48 ? `${r.age_hours.toFixed(0)}h` : `${(r.age_hours / 24).toFixed(0)}d`}
                  </td>
                  <td style={{ padding: '6px 0' }}>{r.is_demo && <Badge text="DEMO" variant="yellow" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Panel>
  )
}

/* ── small control groups ── */
function RangeBtns({ value, onChange }: { value: number; onChange: (d: number) => void }) {
  return <div style={{ display: 'flex', gap: 4 }}>{RANGES.map(r => (
    <button key={r.label} onClick={() => onChange(r.days)} style={btn(value === r.days, 'var(--blue)')}>{r.label}</button>
  ))}</div>
}
function ModeBtns({ value, onChange }: { value: typeof MODES[number]; onChange: (m: typeof MODES[number]) => void }) {
  return <div style={{ display: 'flex', gap: 4 }}>{MODES.map(mo => (
    <button key={mo} onClick={() => onChange(mo)} style={btn(value === mo, 'var(--green)')}>{mo}</button>
  ))}</div>
}
function btn(active: boolean, c: string): React.CSSProperties {
  return {
    padding: '2px 8px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
    fontFamily: "'JetBrains Mono', monospace", letterSpacing: 0.5,
    background: active ? 'rgba(255,255,255,0.06)' : 'transparent',
    color: active ? c : 'var(--text-muted)',
    border: active ? `1px solid ${c}55` : '1px solid transparent',
  }
}
