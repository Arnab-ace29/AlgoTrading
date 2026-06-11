import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Zap } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api } from '../api'
import type { SignalResult } from '../api'
import { KpiCard, Panel, Badge, ScoreBar, SectionTitle, EmptyState } from '../components'
import { CHART_STYLE } from '../theme'

const dirBadge = (d: string) => {
  if (d === 'LONG')  return <Badge text="LONG"    variant="green" />
  if (d === 'SHORT') return <Badge text="SHORT"   variant="red" />
  return               <Badge text="NEUTRAL" variant="neutral" />
}

const regimeColor: Record<string, string> = {
  TRENDING_UP:    'var(--green)',
  TRENDING_DOWN:  'var(--red)',
  MEAN_REVERTING: 'var(--yellow)',
  CHOPPY:         'var(--text-muted)',
}

const RANGES = [
  { label: '1W',  days: 7   },
  { label: '1M',  days: 30  },
  { label: '3M',  days: 90  },
  { label: 'ALL', days: 9999 },
]

export default function Overview() {
  const [equityDays, setEquityDays] = useState(90)

  const { data: daily }   = useQuery({ queryKey: ['daily-stats'], queryFn: api.dailyStats })
  const { data: equity }  = useQuery({ queryKey: ['equity', equityDays], queryFn: () => api.equityCurve(equityDays) })
  const { data: signals } = useQuery({ queryKey: ['scan'], queryFn: () => api.signalScan(), refetchInterval: 10000 })

  const actionable = (signals ?? []).filter((s: SignalResult) => s.actionable)
  const pnl = daily?.gross_pnl ?? 0
  const pnlColor = pnl >= 0 ? 'var(--green)' : 'var(--red)'

  const activeRange = RANGES.find(r => r.days === equityDays) ?? RANGES[2]

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle>
        Command Centre
        <span style={{ fontSize: 11, color: '#3d4155', fontWeight: 400 }}>
          {new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })} IST
        </span>
      </SectionTitle>

      {/* KPI row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <KpiCard label="Today P&L" value={`${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(0)}`}
          sub={`Net ₹${(daily?.net_pnl ?? 0).toFixed(0)}`}
          color={pnlColor} glow />
        <KpiCard label="Trades" value={String(daily?.total_trades ?? 0)}
          sub={`${daily?.wins ?? 0} W  /  ${daily?.losses ?? 0} L`} />
        <KpiCard label="Win Rate" value={`${((daily?.win_rate ?? 0) * 100).toFixed(1)}%`}
          color={(daily?.win_rate ?? 0) >= 0.5 ? 'var(--green)' : 'var(--red)'} />
        <KpiCard label="Actionable Now" value={String(actionable.length)}
          sub="signals crossing threshold" color={actionable.length > 0 ? 'var(--blue)' : undefined} />
      </div>

      {/* Equity curve */}
      <Panel
        title={`Equity Curve · ${activeRange.label}`}
        right={
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {RANGES.map(r => (
              <button key={r.label} onClick={() => setEquityDays(r.days)}
                style={{
                  padding: '2px 8px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
                  fontFamily: "'JetBrains Mono', monospace", letterSpacing: 0.5,
                  background: equityDays === r.days ? 'var(--blue-dim)' : 'transparent',
                  color: equityDays === r.days ? 'var(--blue)' : 'var(--text-muted)',
                  border: equityDays === r.days ? '1px solid rgba(77,166,255,0.3)' : '1px solid transparent',
                }}>
                {r.label}
              </button>
            ))}
          </div>
        }>
        {equity && equity.length > 0 ? (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={equity} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#4da6ff" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#4da6ff" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid {...CHART_STYLE.grid} />
              <XAxis dataKey="date" {...CHART_STYLE.axis} tickFormatter={v => v.slice(5)} />
              <YAxis {...CHART_STYLE.axis} tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} />
              <Tooltip {...CHART_STYLE.tooltip} formatter={(v) => [`₹${Number(v).toLocaleString()}`, 'Equity']} />
              <Area type="monotone" dataKey="equity" stroke="var(--blue)" strokeWidth={1.5} fill="url(#eq)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState msg="No equity history yet — run some trades" />
        )}
      </Panel>

      {/* Signal scanner */}
      <Panel title="Live Signal Scanner"
        right={<span style={{ fontSize: 10, color: '#3d4155' }}>{(signals ?? []).length} symbols · auto-refresh 10s</span>}>
        {(signals ?? []).length === 0 ? (
          <EmptyState msg="No signal data — is FastAPI running on port 8000?" />
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1a1d27' }}>
                {['Symbol', 'Score', 'Direction', 'Regime', 'V-Breakout', 'RSI Mom', 'Status'].map(h => (
                  <th key={h} style={{ padding: '6px 10px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(signals ?? []).map((s: SignalResult) => (
                <tr key={s.symbol}
                  style={{
                    borderBottom: '1px solid #12141b',
                    background: s.actionable ? 'rgba(99,102,241,0.04)' : 'transparent',
                  }}>
                  <td style={{ padding: '7px 10px 7px 0', fontWeight: 700, color: '#e2e4e9', fontSize: 13 }}>{s.symbol}</td>
                  <td style={{ padding: '7px 10px 7px 0' }}><ScoreBar score={s.composite_score} /></td>
                  <td style={{ padding: '7px 10px 7px 0' }}>{dirBadge(s.direction)}</td>
                  <td style={{ padding: '7px 10px 7px 0' }}>
                    <span style={{ fontSize: 11, color: regimeColor[s.regime] ?? '#6b7280', fontWeight: 500 }}>
                      {s.regime?.replace('_', ' ')}
                    </span>
                  </td>
                  <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 11,
                    color: (s.signal_scores?.vwap_breakout ?? 0) > 0 ? '#4ade80' : '#f87171' }}>
                    {((s.signal_scores?.vwap_breakout ?? 0) > 0 ? '+' : '')}{(s.signal_scores?.vwap_breakout ?? 0).toFixed(3)}
                  </td>
                  <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 11,
                    color: (s.signal_scores?.rsi_momentum ?? 0) > 0 ? '#4ade80' : '#f87171' }}>
                    {((s.signal_scores?.rsi_momentum ?? 0) > 0 ? '+' : '')}{(s.signal_scores?.rsi_momentum ?? 0).toFixed(3)}
                  </td>
                  <td style={{ padding: '7px 0 7px 0' }}>
                    {s.actionable
                      ? <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: 'var(--green)', fontWeight: 700, textShadow: '0 0 6px rgba(0,232,123,0.5)' }}>
                          <Zap size={10} /> FIRE
                        </span>
                      : <span style={{ fontSize: 9, color: 'var(--border-hi)' }}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}
