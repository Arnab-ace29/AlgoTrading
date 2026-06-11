import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Zap, Bot, Pause, Activity, ShieldOff } from 'lucide-react'
import { api } from '../api'
import type { SignalResult } from '../api'
import { Panel, Badge, SectionTitle, EmptyState } from '../components'

const regimeColor = (r?: string) => {
  if (!r) return 'var(--text-muted)'
  if (r.includes('UP'))   return 'var(--green)'
  if (r.includes('DOWN')) return 'var(--red)'
  if (r.includes('MEAN')) return 'var(--yellow)'
  return 'var(--text-muted)'
}

export default function Live() {
  const qc = useQueryClient()

  const { data: status, isError } = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 3000 })
  const { data: positions } = useQuery({ queryKey: ['open-positions'], queryFn: api.openPositions, refetchInterval: 3000 })
  const { data: signals, isFetching: scanning, refetch: scan } =
    useQuery({ queryKey: ['scan-live'], queryFn: () => api.signalScan(), refetchInterval: 15000 })

  const tradingEnabled = status?.trading_enabled ?? true
  const killed = status?.circuit_breaker?.kill_switch_active ?? false
  const halted = status?.circuit_breaker?.halted ?? false
  const blackout = status?.circuit_breaker?.in_blackout ?? false

  const toggleTrading = useMutation({
    mutationFn: () => api.setTrading(!tradingEnabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })

  const engineState = killed ? 'KILLED' : halted ? 'HALTED' : !tradingEnabled ? 'PAUSED'
    : blackout ? 'BLACKOUT' : 'ACTIVE'
  const engineColor = engineState === 'ACTIVE' ? 'var(--green)'
    : engineState === 'PAUSED' || engineState === 'BLACKOUT' ? 'var(--yellow)' : 'var(--red)'

  const pnl = status?.today_pnl ?? 0
  const open = positions ?? []

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SectionTitle>
          Live Trading
          <span style={{ fontSize: 9, color: isError ? 'var(--red)' : 'var(--green)', letterSpacing: 1 }}>
            {isError ? '○ API OFFLINE' : '● CONNECTED'}
          </span>
        </SectionTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            className={tradingEnabled ? 't-btn t-btn-green' : 't-btn t-btn-yellow'}
            style={{ display: 'flex', alignItems: 'center', gap: 5 }}
            onClick={() => toggleTrading.mutate()} disabled={toggleTrading.isPending || killed}>
            {tradingEnabled ? <Bot size={10} /> : <Pause size={10} />}
            {tradingEnabled ? 'AUTO' : 'PAUSED'}
          </button>
          <button className="t-btn" style={{ display: 'flex', alignItems: 'center', gap: 5 }}
            onClick={() => scan()} disabled={scanning}>
            {scanning ? <RefreshCw size={10} className="spinning" /> : <Zap size={10} />}
            SCAN NOW
          </button>
        </div>
      </div>

      {/* Status bar */}
      <div className="t-panel" style={{ padding: '12px 16px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
          <Stat label="ENGINE STATE">
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 700, color: engineColor }}>
              {killed && <ShieldOff size={12} />}
              {engineState}
            </span>
          </Stat>
          <Stat label="MODE">
            <span style={{ fontSize: 13, fontWeight: 700, color: status?.upstox_mode === 'live' ? 'var(--blue)' : 'var(--yellow)' }}>
              {(status?.upstox_mode ?? '—').toUpperCase()}{status?.paper_mode ? ' · PAPER' : ''}
            </span>
          </Stat>
          <Stat label="SESSION P&L (NET)">
            <span style={{ fontSize: 14, fontWeight: 700, color: pnl >= 0 ? 'var(--green)' : 'var(--red)',
              textShadow: `0 0 8px ${pnl >= 0 ? 'rgba(0,232,123,0.4)' : 'rgba(255,62,62,0.4)'}` }}>
              {pnl >= 0 ? '+' : ''}₹{pnl.toLocaleString('en-IN')}
            </span>
          </Stat>
          <Stat label="TRADES TODAY">
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
              {status?.today_trades ?? 0}
              <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>
                / {status?.circuit_breaker?.max_trades ?? '—'}
              </span>
            </span>
          </Stat>
          <Stat label="WIN RATE">
            <span style={{ fontSize: 14, fontWeight: 700, color: (status?.today_win_rate ?? 0) >= 0.5 ? 'var(--green)' : 'var(--red)' }}>
              {((status?.today_win_rate ?? 0) * 100).toFixed(0)}%
            </span>
          </Stat>
        </div>
        {(halted || blackout || killed) && (
          <div style={{ marginTop: 10, fontSize: 10, color: 'var(--yellow)', letterSpacing: 0.5 }}>
            {killed ? '⊘ Kill switch active — positions flattened, entries halted.'
              : halted ? `🛑 ${status?.circuit_breaker?.halt_reason || 'Trading halted'}`
              : `⏱ ${status?.circuit_breaker?.blackout_reason || 'Blackout window'}`}
          </div>
        )}
      </div>

      {/* Open positions */}
      <Panel title={`Open Positions (${open.length})`} accent="var(--green)"
        right={<span style={{ fontSize: 9, color: 'var(--text-muted)' }}>from trade log</span>}>
        {open.length === 0
          ? <EmptyState msg="No open positions" />
          : <table>
              <thead><tr>
                {['Time', 'Symbol', 'Side', 'Qty', 'Entry', 'SL', 'Target', 'Score', 'Regime'].map(h => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {open.map(p => (
                  <tr key={p.trade_id}>
                    <td style={{ color: 'var(--text-dim)', fontSize: 10 }}>{p.entry_time?.slice(11, 16) ?? '—'}</td>
                    <td style={{ fontWeight: 700, color: 'var(--text)' }}>{p.symbol}</td>
                    <td><Badge text={p.side} variant={p.side === 'BUY' ? 'green' : 'red'} /></td>
                    <td style={{ color: 'var(--text-dim)' }}>{p.qty}</td>
                    <td style={{ color: 'var(--text-dim)' }}>₹{p.entry_price?.toFixed(1)}</td>
                    <td style={{ color: 'var(--red)' }}>₹{p.sl_price?.toFixed(1)}</td>
                    <td style={{ color: 'var(--green)' }}>₹{p.target_price?.toFixed(1)}</td>
                    <td style={{ fontFamily: 'inherit', color: 'var(--blue)' }}>{p.entry_score?.toFixed(3) ?? '—'}</td>
                    <td style={{ fontSize: 10, color: regimeColor(p.regime_at_entry) }}>{p.regime_at_entry?.replace(/_/g, ' ') ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
      </Panel>

      {/* Signal scanner */}
      <Panel title="Signal Scanner" accent="var(--blue)"
        right={<span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{(signals ?? []).length} symbols · 15s</span>}>
        {(signals ?? []).length === 0
          ? <EmptyState msg="No signal data — is the API + data feed running?" />
          : <table>
              <thead><tr>{['Symbol', 'Score', 'Dir', 'Regime', 'Fire?'].map(h => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {(signals ?? []).slice(0, 15).map((s: SignalResult) => (
                  <tr key={s.symbol} style={{ background: s.actionable ? 'rgba(0,232,123,0.04)' : 'transparent' }}>
                    <td style={{ fontWeight: 700 }}>{s.symbol}</td>
                    <td style={{ fontFamily: 'inherit', color: s.composite_score > 0 ? 'var(--green)' : 'var(--red)', fontSize: 11 }}>
                      {s.composite_score > 0 ? '+' : ''}{s.composite_score.toFixed(3)}
                    </td>
                    <td><Badge text={s.direction} variant={s.direction === 'LONG' ? 'green' : s.direction === 'SHORT' ? 'red' : 'neutral'} /></td>
                    <td style={{ fontSize: 10, color: regimeColor(s.regime) }}>{s.regime?.replace(/_/g, ' ')}</td>
                    <td>
                      {s.actionable
                        ? <span style={{ color: 'var(--green)', fontWeight: 700, fontSize: 9 }}>
                            <Activity size={9} style={{ display: 'inline', marginRight: 3 }} />FIRE
                          </span>
                        : <span style={{ color: 'var(--border-hi)', fontSize: 9 }}>—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>}
      </Panel>
    </div>
  )
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="t-label" style={{ marginBottom: 5 }}>{label}</div>
      {children}
    </div>
  )
}
