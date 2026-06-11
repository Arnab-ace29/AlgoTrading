import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Check } from 'lucide-react'
import { api } from '../api'
import type { SignalResult } from '../api'
import { Panel, Badge, ScoreBar, SectionTitle, EmptyState } from '../components'

const SIGNALS = [
  { name: 'vwap_breakout',  label: 'VWAP Breakout',   desc: 'Price vs VWAP + EMA + Volume surge' },
  { name: 'rsi_momentum',   label: 'RSI Momentum',     desc: 'RSI cross-50 + MACD + ROC' },
  { name: 'mean_reversion', label: 'Mean Reversion',   desc: 'BB stretch + oversold/overbought count' },
]

const regimeColors: Record<string, string> = {
  TRENDING_UP: '#4ade80', TRENDING_DOWN: '#f87171', MEAN_REVERTING: '#facc15', CHOPPY: '#6b7280',
}

function MonoScore({ v }: { v: number }) {
  const c = v > 0.05 ? '#4ade80' : v < -0.05 ? '#f87171' : '#3d4155'
  return <span style={{ fontFamily: 'monospace', fontSize: 12, color: c }}>{v > 0 ? '+' : ''}{v.toFixed(3)}</span>
}

export default function Signals() {
  const qc = useQueryClient()
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(SIGNALS.map(s => [s.name, true]))
  )
  const [localW, setLocalW] = useState<Record<string, number>>({})
  const [saved, setSaved] = useState(false)

  const { data: signals, isFetching, refetch } = useQuery({
    queryKey: ['scan-full'], queryFn: () => api.signalScan(), refetchInterval: 10000,
  })
  const { data: weights } = useQuery({ queryKey: ['weights'], queryFn: api.signalWeights })

  const updateW = useMutation({
    mutationFn: api.updateWeights,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['weights'] }); setSaved(true); setTimeout(() => setSaved(false), 2000) },
  })
  const toggleM = useMutation({
    mutationFn: ({ name, val }: { name: string; val: boolean }) => api.toggleSignal(name, val),
  })

  const w = { ...weights, ...localW }

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SectionTitle>Signal Control Panel</SectionTitle>
        <button onClick={() => refetch()} style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px',
          background: '#13151c', border: '1px solid #1e2130', borderRadius: 6,
          color: '#6b7280', fontSize: 12, cursor: 'pointer',
        }}>
          <RefreshCw size={12} style={isFetching ? { animation: 'spin 0.7s linear infinite' } : {}} />
          Refresh
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 14 }}>
        {/* Weight sliders */}
        <Panel title="Signal Weights">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {SIGNALS.map(({ name, label, desc }) => {
              const val = w[name] ?? 0
              const on = enabled[name]
              return (
                <div key={name} style={{ opacity: on ? 1 : 0.4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, alignItems: 'center' }}>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#c9cdd8' }}>{label}</div>
                      <div style={{ fontSize: 10, color: '#3d4155', marginTop: 1 }}>{desc}</div>
                    </div>
                    <button onClick={() => {
                      const next = !on
                      setEnabled(p => ({ ...p, [name]: next }))
                      toggleM.mutate({ name, val: next })
                    }} style={{
                      width: 32, height: 18, borderRadius: 9, cursor: 'pointer',
                      background: on ? '#6366f1' : '#1e2130', border: 'none',
                      position: 'relative', transition: 'background 0.2s',
                    }}>
                      <span style={{
                        position: 'absolute', top: 2, borderRadius: '50%',
                        width: 14, height: 14, background: '#fff',
                        left: on ? 16 : 2, transition: 'left 0.2s',
                      }} />
                    </button>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <input type="range" min={0} max={1} step={0.05} value={val} style={{ flex: 1 }}
                      onChange={e => setLocalW(p => ({ ...p, [name]: parseFloat(e.target.value) }))}
                      disabled={!on} />
                    <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 700, color: '#6366f1', minWidth: 38, textAlign: 'right' }}>
                      {(val * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              )
            })}
            <button onClick={() => updateW.mutate(localW)} disabled={Object.keys(localW).length === 0}
              style={{
                padding: '8px 0', borderRadius: 7, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                background: saved ? 'rgba(74,222,128,0.15)' : '#6366f1',
                color: saved ? '#4ade80' : '#fff', border: saved ? '1px solid #4ade80' : 'none',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                opacity: Object.keys(localW).length === 0 ? 0.4 : 1,
                transition: 'background 0.2s',
              }}>
              {saved ? <><Check size={13} /> Saved!</> : 'Apply Weights'}
            </button>
          </div>
        </Panel>

        {/* Scanner table */}
        <Panel title="Scanner Results"
          right={<span style={{ fontSize: 10, color: '#3d4155' }}>{(signals ?? []).length} symbols · 10s refresh</span>}>
          {(signals ?? []).length === 0 ? (
            <EmptyState msg="No data — FastAPI not running?" />
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1a1d27' }}>
                  {['Symbol','Score','VWAP','RSI','MeanRev','Regime','Dir'].map(h => (
                    <th key={h} style={{ padding: '6px 10px 6px 0', textAlign: 'left', fontSize: 10, color: '#3d4155', fontWeight: 600, letterSpacing: 0.6, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(signals ?? []).map((s: SignalResult) => (
                  <tr key={s.symbol} style={{
                    borderBottom: '1px solid #12141b',
                    background: s.actionable ? 'rgba(99,102,241,0.05)' : 'transparent',
                  }}>
                    <td style={{ padding: '7px 10px 7px 0', fontWeight: 700, color: '#e2e4e9', fontSize: 13 }}>{s.symbol}</td>
                    <td style={{ padding: '7px 10px 7px 0' }}><ScoreBar score={s.composite_score} /></td>
                    <td style={{ padding: '7px 10px 7px 0' }}><MonoScore v={s.signal_scores?.vwap_breakout ?? 0} /></td>
                    <td style={{ padding: '7px 10px 7px 0' }}><MonoScore v={s.signal_scores?.rsi_momentum ?? 0} /></td>
                    <td style={{ padding: '7px 10px 7px 0' }}><MonoScore v={s.signal_scores?.mean_reversion ?? 0} /></td>
                    <td style={{ padding: '7px 10px 7px 0' }}>
                      <span style={{ fontSize: 11, fontWeight: 500, color: regimeColors[s.regime] ?? '#6b7280' }}>
                        {s.regime?.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td style={{ padding: '7px 0 7px 0' }}>
                      {s.direction === 'LONG'  && <Badge text="LONG"    variant="green" />}
                      {s.direction === 'SHORT' && <Badge text="SHORT"   variant="red" />}
                      {s.direction === 'NEUTRAL' && <Badge text="—"     variant="neutral" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  )
}
