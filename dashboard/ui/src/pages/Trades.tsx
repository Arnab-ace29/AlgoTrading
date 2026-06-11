import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, ReferenceLine } from 'recharts'
import { api } from '../api'
import type { Trade, PerfRow } from '../api'
import { Panel, Badge, SectionTitle, EmptyState } from '../components'
import { CHART_STYLE } from '../theme'

const PERF_RANGES = [
  { label: '1W',  days: 7  },
  { label: '2W',  days: 14 },
  { label: '1M',  days: 30 },
  { label: '3M',  days: 90 },
  { label: 'ALL', days: 9999 },
]

export default function Trades() {
  const [perfDays, setPerfDays] = useState(30)

  const { data: trades }   = useQuery({ queryKey: ['trades'],           queryFn: () => api.trades(500) })
  const { data: perf }     = useQuery({ queryKey: ['perf-history', perfDays], queryFn: () => api.performanceHistory(perfDays) })
  const { data: byStrat }  = useQuery({ queryKey: ['by-strategy'],      queryFn: api.byStrategy })

  const perfChartData = [...(perf ?? [])].reverse()

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle>Trade History</SectionTitle>

      {/* Daily P&L chart */}
      <Panel
        title={`Daily P&L · ${PERF_RANGES.find(r => r.days === perfDays)?.label ?? ''}`}
        right={
          <div style={{ display: 'flex', gap: 4 }}>
            {PERF_RANGES.map(r => (
              <button key={r.label} onClick={() => setPerfDays(r.days)}
                style={{
                  padding: '2px 8px', fontSize: 9, fontWeight: 700, cursor: 'pointer',
                  fontFamily: "'JetBrains Mono', monospace", letterSpacing: 0.5,
                  background: perfDays === r.days ? 'rgba(0,232,123,0.1)' : 'transparent',
                  color: perfDays === r.days ? 'var(--green)' : 'var(--text-muted)',
                  border: perfDays === r.days ? '1px solid rgba(0,232,123,0.25)' : '1px solid transparent',
                }}>
                {r.label}
              </button>
            ))}
          </div>
        }>
        {perfChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={perfChartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid {...CHART_STYLE.grid} vertical={false} />
              <XAxis dataKey="date" {...CHART_STYLE.axis} tickFormatter={v => v.slice(5)} />
              <YAxis {...CHART_STYLE.axis} tickFormatter={v => `₹${v}`} />
              <ReferenceLine y={0} stroke="#2a2d35" />
              <Tooltip {...CHART_STYLE.tooltip} formatter={(v) => [`₹${Number(v).toFixed(0)}`, 'P&L']} />
              <Bar dataKey="gross_pnl" radius={[3, 3, 0, 0]}>
                {perfChartData.map((row: PerfRow, i: number) => (
                  <Cell key={i} fill={row.gross_pnl >= 0 ? '#4ade80' : '#f87171'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState msg="No daily P&L history yet" />
        )}
      </Panel>

      {/* Strategy breakdown + trade log side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: byStrat && byStrat.length > 0 ? '280px 1fr' : '1fr', gap: 14 }}>
        {byStrat && byStrat.length > 0 && (
          <Panel title="By Strategy">
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1a1d27' }}>
                  {['Strategy','Trades','Win%','P&L'].map(h => (
                    <th key={h} style={{ padding: '6px 10px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {byStrat.map((s, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #12141b' }}>
                    <td style={{ padding: '7px 10px 7px 0', color: '#c9cdd8', fontSize: 12 }}>{s.strategy}</td>
                    <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 12, color: '#6b7280' }}>{s.total_trades}</td>
                    <td style={{ padding: '7px 10px 7px 0', fontFamily: 'monospace', fontSize: 12,
                      color: s.win_rate >= 0.5 ? '#4ade80' : '#f87171' }}>
                      {(s.win_rate * 100).toFixed(0)}%
                    </td>
                    <td style={{ padding: '7px 0 7px 0', fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
                      color: s.total_pnl >= 0 ? '#4ade80' : '#f87171' }}>
                      {s.total_pnl >= 0 ? '+' : ''}₹{s.total_pnl.toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}

        {/* Trade log */}
        <Panel title="Trade Log" right={<span style={{ fontSize: 10, color: '#3d4155' }}>{(trades ?? []).length} records</span>}>
          {(trades ?? []).length === 0 ? (
            <EmptyState msg="No closed trades yet" />
          ) : (
            <div style={{ overflowY: 'auto', maxHeight: 360 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead style={{ position: 'sticky', top: 0, background: '#0d0f16' }}>
                  <tr style={{ borderBottom: '1px solid #1a1d27' }}>
                    {['Symbol','Side','Entry','Exit','P&L','P&L%','Time'].map(h => (
                      <th key={h} style={{ padding: '6px 10px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(trades ?? []).slice(0, 100).map((t: Trade) => (
                    <tr key={t.trade_id} style={{ borderBottom: '1px solid #0f1117' }}>
                      <td style={{ padding: '6px 10px 6px 0', fontWeight: 700, color: '#e2e4e9', fontSize: 12 }}>{t.symbol}</td>
                      <td style={{ padding: '6px 10px 6px 0' }}>
                        <Badge text={t.side} variant={t.side === 'BUY' ? 'green' : 'red'} />
                      </td>
                      <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 11, color: '#6b7280' }}>₹{t.entry_price?.toFixed(1)}</td>
                      <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 11, color: '#6b7280' }}>₹{t.exit_price?.toFixed(1)}</td>
                      <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 12, fontWeight: 700,
                        color: (t.pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                        {(t.pnl ?? 0) >= 0 ? '+' : ''}₹{(t.pnl ?? 0).toFixed(0)}
                      </td>
                      <td style={{ padding: '6px 10px 6px 0', fontFamily: 'monospace', fontSize: 11,
                        color: (t.pnl_pct ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                        {(t.pnl_pct ?? 0) >= 0 ? '+' : ''}{((t.pnl_pct ?? 0) * 100).toFixed(2)}%
                      </td>
                      <td style={{ padding: '6px 0 6px 0', fontSize: 10, color: '#3d4155' }}>{t.entry_time?.slice(5, 16)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
