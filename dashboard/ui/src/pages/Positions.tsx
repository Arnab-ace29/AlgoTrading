import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Position } from '../api'
import { Panel, Badge, SectionTitle, EmptyState, Spinner } from '../components'

const regimeColor = (r?: string) => {
  if (!r) return 'var(--text-muted)'
  if (r.includes('UP'))   return 'var(--green)'
  if (r.includes('DOWN')) return 'var(--red)'
  if (r.includes('MEAN')) return 'var(--yellow)'
  return 'var(--text-muted)'
}

export default function Positions() {
  const { data: positions, isLoading } = useQuery({
    queryKey: ['open-positions'], queryFn: api.openPositions, refetchInterval: 5000,
  })

  const list = positions ?? []
  const totalRisk = list.reduce((s: number, p: Position) =>
    s + Math.abs((p.entry_price ?? 0) - (p.sl_price ?? 0)) * (p.qty ?? 0), 0)

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SectionTitle>Open Positions</SectionTitle>
        {list.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Open risk (Σ to SL):</span>
            <span style={{ fontSize: 14, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: 'var(--yellow)' }}>
              ₹{totalRisk.toFixed(0)}
            </span>
          </div>
        )}
      </div>

      <Panel title={`${list.length} Open Position${list.length !== 1 ? 's' : ''}`}
        accent="var(--green)"
        right={<span style={{ fontSize: 10, color: 'var(--green)' }} className="t-pulse">● LIVE</span>}>
        {isLoading ? <Spinner /> :
         list.length === 0 ? <EmptyState msg="No open positions right now" /> : (
          <table>
            <thead>
              <tr>
                {['Symbol', 'Side', 'Qty', 'Entry', 'SL', 'Target', 'R:R', 'Score', 'Regime', 'Time'].map(h => <th key={h}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {list.map((p: Position) => {
                const risk   = Math.abs((p.entry_price ?? 0) - (p.sl_price ?? 0))
                const reward = Math.abs((p.target_price ?? 0) - (p.entry_price ?? 0))
                const rr = risk > 0 ? reward / risk : 0
                return (
                  <tr key={p.trade_id}>
                    <td style={{ fontWeight: 700, color: 'var(--text)' }}>{p.symbol}</td>
                    <td><Badge text={p.side} variant={p.side === 'BUY' ? 'green' : 'red'} /></td>
                    <td style={{ color: 'var(--text-dim)' }}>{p.qty}</td>
                    <td style={{ color: 'var(--text-dim)' }}>₹{p.entry_price?.toFixed(2)}</td>
                    <td style={{ color: 'var(--red)' }}>₹{p.sl_price?.toFixed(2)}</td>
                    <td style={{ color: 'var(--green)' }}>₹{p.target_price?.toFixed(2)}</td>
                    <td style={{ color: 'var(--text-dim)' }}>{rr ? `${rr.toFixed(2)}:1` : '—'}</td>
                    <td style={{ fontFamily: 'inherit', color: 'var(--blue)' }}>{p.entry_score?.toFixed(3) ?? '—'}</td>
                    <td style={{ fontSize: 10, color: regimeColor(p.regime_at_entry) }}>{p.regime_at_entry?.replace(/_/g, ' ') ?? '—'}</td>
                    <td style={{ fontSize: 10, color: 'var(--text-muted)' }}>{p.entry_time?.slice(5, 16) ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Panel>

      <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 0.3 }}>
        Live LTP / unrealised P&amp;L per position requires the tick feed wiring (tracked on the Roadmap as a pending item).
      </div>
    </div>
  )
}
