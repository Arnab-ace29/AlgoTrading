import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Play, Loader2 } from 'lucide-react'
import { api } from '../api'
import type { BacktestResult } from '../api'
import { Panel, SectionTitle, EmptyState } from '../components'

const ALL_SYMBOLS = ['RELIANCE','TCS','INFY','HDFCBANK','ICICIBANK','SBIN','AXISBANK','WIPRO','HINDUNILVR','BAJFINANCE']

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: '#0a0b0e', borderRadius: 8, padding: '10px 14px', border: '1px solid #1a1d27' }}>
      <div style={{ fontSize: 9, color: '#3d4155', fontWeight: 600, letterSpacing: 0.8, textTransform: 'uppercase', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'monospace', color: color ?? '#e2e4e9' }}>{value}</div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 5 }}>{children}</div>
}

export default function Backtest() {
  // Lazy initializer keeps the impure date calls out of render (react-hooks/purity).
  const [form, setForm] = useState(() => {
    const today      = new Date().toISOString().slice(0, 10)
    const oneYearAgo = new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10)
    return { symbols: ALL_SYMBOLS, from_date: oneYearAgo, to_date: today, walk_forward: true, n_folds: 5 }
  })

  const { data: result, refetch } = useQuery({
    queryKey: ['bt-result'], queryFn: api.backtestResult, refetchInterval: 3000,
  })
  const { data: history } = useQuery({ queryKey: ['bt-history'], queryFn: api.backtestHistory })

  const runMut = useMutation({
    mutationFn: api.runBacktest,
    onSuccess: () => setTimeout(() => refetch(), 2000),
  })

  const btResult = result && 'run_id' in result ? result as BacktestResult : null

  const toggleSym = (s: string) => setForm(p => ({
    ...p,
    symbols: p.symbols.includes(s) ? p.symbols.filter(x => x !== s) : [...p.symbols, s],
  }))

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <SectionTitle>Backtest Runner</SectionTitle>

      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 14, alignItems: 'start' }}>

        {/* Config */}
        <Panel title="Configuration">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <Label>Date Range</Label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <input type="date" value={form.from_date} style={{ width: '100%' }}
                  onChange={e => setForm(p => ({ ...p, from_date: e.target.value }))} />
                <input type="date" value={form.to_date} style={{ width: '100%' }}
                  onChange={e => setForm(p => ({ ...p, to_date: e.target.value }))} />
              </div>
            </div>

            <div>
              <Label>Walk-Forward Folds</Label>
              <input type="number" min={1} max={10} value={form.n_folds} style={{ width: '100%' }}
                onChange={e => setForm(p => ({ ...p, n_folds: parseInt(e.target.value) }))} />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" id="wf" checked={form.walk_forward}
                onChange={e => setForm(p => ({ ...p, walk_forward: e.target.checked }))} />
              <label htmlFor="wf" style={{ fontSize: 12, color: '#9ca3af', cursor: 'pointer' }}>Walk-forward test</label>
            </div>

            <div>
              <Label>Symbols ({form.symbols.length} / {ALL_SYMBOLS.length})</Label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {ALL_SYMBOLS.map(s => {
                  const sel = form.symbols.includes(s)
                  return (
                    <button key={s} onClick={() => toggleSym(s)} style={{
                      fontSize: 10, fontWeight: 600, padding: '3px 8px', borderRadius: 4,
                      cursor: 'pointer', transition: 'all 0.15s',
                      background: sel ? 'rgba(99,102,241,0.2)' : '#0a0b0e',
                      color: sel ? '#818cf8' : '#3d4155',
                      border: sel ? '1px solid rgba(99,102,241,0.4)' : '1px solid #1a1d27',
                    }}>{s}</button>
                  )
                })}
              </div>
            </div>

            <button onClick={() => runMut.mutate(form)}
              disabled={runMut.isPending || form.symbols.length === 0}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
                padding: '10px 0', borderRadius: 7, fontSize: 12, fontWeight: 700,
                background: runMut.isPending ? '#1e2130' : 'linear-gradient(135deg,#6366f1,#8b5cf6)',
                color: runMut.isPending ? '#5a5e72' : '#fff', border: 'none', cursor: 'pointer',
                opacity: form.symbols.length === 0 ? 0.4 : 1,
              }}>
              {runMut.isPending ? <><Loader2 size={13} style={{ animation: 'spin 0.7s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Backtest</>}
            </button>
            {runMut.isSuccess && !runMut.isPending && (
              <div style={{ fontSize: 11, color: '#4ade80', textAlign: 'center' }}>
                ✓ Started — results update every 3s
              </div>
            )}
          </div>
        </Panel>

        {/* Results */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {btResult ? (
            <Panel title="Latest Result" right={<span style={{ fontSize: 10, fontFamily: 'monospace', color: '#3d4155' }}>#{btResult.run_id}</span>}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 14 }}>
                <Metric label="Total Return"
                  value={`${btResult.total_return >= 0 ? '+' : ''}${btResult.total_return?.toFixed(2)}%`}
                  color={btResult.total_return >= 0 ? '#4ade80' : '#f87171'} />
                <Metric label="Sharpe Ratio"
                  value={btResult.sharpe?.toFixed(3)}
                  color={btResult.sharpe >= 1.5 ? '#4ade80' : btResult.sharpe >= 1 ? '#facc15' : '#f87171'} />
                <Metric label="Max Drawdown"
                  value={`${btResult.max_drawdown?.toFixed(2)}%`}
                  color={btResult.max_drawdown <= 10 ? '#4ade80' : btResult.max_drawdown <= 20 ? '#facc15' : '#f87171'} />
                <Metric label="Win Rate"
                  value={`${btResult.win_rate?.toFixed(1)}%`}
                  color={btResult.win_rate >= 50 ? '#4ade80' : '#f87171'} />
                <Metric label="Total Trades"  value={String(btResult.total_trades)} />
                <Metric label="Avg Trade"
                  value={`${btResult.avg_trade_pct >= 0 ? '+' : ''}${btResult.avg_trade_pct?.toFixed(2)}%`}
                  color={btResult.avg_trade_pct >= 0 ? '#4ade80' : '#f87171'} />
              </div>
              <div style={{
                padding: '10px 12px', borderRadius: 6,
                background: btResult.sharpe >= 1 ? 'rgba(74,222,128,0.05)' : 'rgba(248,113,113,0.05)',
                border: `1px solid ${btResult.sharpe >= 1 ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)'}`,
                fontSize: 11, color: '#9ca3af',
              }}>
                Sharpe {btResult.sharpe >= 1.5
                  ? <span style={{ color: '#4ade80' }}>≥ 1.5 — strong risk-adjusted return</span>
                  : btResult.sharpe >= 1.0
                  ? <span style={{ color: '#facc15' }}>≥ 1.0 — acceptable</span>
                  : <span style={{ color: '#f87171' }}>{'< 1.0 — needs improvement'}</span>}
              </div>
            </Panel>
          ) : (
            <Panel title="Latest Result">
              <EmptyState msg="No results yet — configure and run a backtest" />
            </Panel>
          )}

          {/* History */}
          {(history ?? []).length > 0 && (
            <Panel title="Run History" right={<span style={{ fontSize: 10, color: '#3d4155' }}>{(history ?? []).length} runs</span>}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #1a1d27' }}>
                    {['Run ID','Time','Return','Sharpe','Drawdown'].map(h => (
                      <th key={h} style={{ padding: '6px 12px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(history ?? []).map(r => (
                    <tr key={r.run_id} style={{ borderBottom: '1px solid #12141b' }}>
                      <td style={{ padding: '7px 12px 7px 0', fontFamily: 'monospace', fontSize: 11, color: '#6366f1' }}>{r.run_id}</td>
                      <td style={{ padding: '7px 12px 7px 0', fontSize: 10, color: '#3d4155' }}>{r.run_time?.slice(0, 16)}</td>
                      <td style={{ padding: '7px 12px 7px 0', fontFamily: 'monospace', fontSize: 12, fontWeight: 600,
                        color: r.total_return >= 0 ? '#4ade80' : '#f87171' }}>
                        {r.total_return >= 0 ? '+' : ''}{r.total_return?.toFixed(2)}%
                      </td>
                      <td style={{ padding: '7px 12px 7px 0', fontFamily: 'monospace', fontSize: 12,
                        color: r.sharpe >= 1 ? '#4ade80' : '#facc15' }}>
                        {r.sharpe?.toFixed(2)}
                      </td>
                      <td style={{ padding: '7px 0 7px 0', fontFamily: 'monospace', fontSize: 11, color: '#6b7280' }}>—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
