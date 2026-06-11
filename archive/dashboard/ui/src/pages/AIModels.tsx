import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api } from '../api'
import type { ModelInfo } from '../api'
import { Panel, KpiCard, SectionTitle, EmptyState, Spinner } from '../components'

function ModelCard({ m }: { m: ModelInfo }) {
  return (
    <div className="t-panel" style={{ overflow: 'hidden' }}>
      <div className="t-section-head" style={{ borderLeft: `2px solid ${m.loaded ? 'var(--green)' : 'var(--text-muted)'}` }}>
        <span style={{ color: m.loaded ? 'var(--green)' : 'var(--text-muted)' }}>{m.label}</span>
        <span style={{
          display: 'inline-block', width: 6, height: 6,
          background: m.loaded ? 'var(--green)' : 'var(--red)',
        }} />
      </div>
      <div style={{ padding: '12px 14px' }}>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: 0.5 }}>{m.description}</div>
        {m.loaded ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px' }}>
            <Field k="File" v={m.file} />
            <Field k="Size" v={`${m.size_kb} KB`} />
            <Field k="Last trained" v={m.modified ? m.modified.slice(0, 16).replace('T', ' ') : '—'} />
            <Field k="Status" v="LOADED" />
          </div>
        ) : (
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>NOT TRAINED — run the training command below</div>
        )}
      </div>
    </div>
  )
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 0.8 }}>{k}</div>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', marginTop: 1, wordBreak: 'break-all' }}>{v}</div>
    </div>
  )
}

export default function AIModels() {
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['model-status'], queryFn: api.modelStatus, refetchInterval: 30000,
  })

  if (isLoading) return <Spinner />

  const models = data?.models ?? []
  const log = data?.training_log ?? []
  const md = data?.models_dir
  const modelsDirShort = md ? '…/' + md.split('/').slice(-2).join('/') : '—'

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SectionTitle>AI Models</SectionTitle>
        <button className="t-btn" style={{ display: 'flex', alignItems: 'center', gap: 5 }} onClick={() => refetch()}>
          <RefreshCw size={10} className={isFetching ? 'spinning' : ''} />
          REFRESH
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
        <KpiCard label="Models Loaded" value={`${data?.loaded_count ?? 0} / ${data?.total_count ?? 0}`}
          color={(data?.loaded_count ?? 0) > 0 ? 'var(--green)' : 'var(--text-dim)'} />
        <KpiCard label="Training Runs Logged" value={String(log.length)} />
        <KpiCard label="Models Dir" value={modelsDirShort} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
        {models.map(m => <ModelCard key={m.file} m={m} />)}
      </div>

      {/* Training log */}
      <Panel title="Training Log" accent="var(--blue)">
        {log.length === 0
          ? <EmptyState msg="No training runs logged yet" />
          : <table>
              <thead><tr>{['Time', 'Model', 'Train AUC', 'Val AUC', 'Samples', 'Features'].map(h => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {log.map((r, i) => (
                  <tr key={r.run_id ?? i}>
                    <td style={{ fontSize: 10, color: 'var(--text-dim)' }}>{String(r.run_time).slice(0, 16).replace('T', ' ')}</td>
                    <td style={{ fontWeight: 600 }}>{r.model_name}</td>
                    <td style={{ fontFamily: 'inherit', color: 'var(--text-dim)' }}>{r.train_auc != null ? Number(r.train_auc).toFixed(3) : '—'}</td>
                    <td style={{ fontFamily: 'inherit', color: (r.val_auc ?? 0) >= 0.58 ? 'var(--green)' : 'var(--yellow)' }}>
                      {r.val_auc != null ? Number(r.val_auc).toFixed(3) : '—'}
                    </td>
                    <td style={{ color: 'var(--text-dim)' }}>{r.n_samples ?? '—'}</td>
                    <td style={{ color: 'var(--text-dim)' }}>{r.features_used ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
      </Panel>

      {/* Real training commands (scripts that exist in the repo) */}
      <Panel title="Training Commands" accent="var(--blue)">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
          {[
            ['Macro XGBoost',    'python models/train_macro.py'],
            ['Micro XGBoost',    'python models/train_micro.py'],
            ['Strategy Outcomes', 'python models/train_outcomes.py'],
            ['RL Entry Agent',   'python models/train_rl_entry.py'],
            ['RL Exit Agent',    'python models/train_rl_on_journeys.py'],
            ['Daily Retrain (all)', 'python scripts/retrain_daily.py'],
          ].map(([label, cmd]) => (
            <div key={label} style={{ background: 'var(--bg)', border: '1px solid var(--border)', padding: '10px 12px' }}>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 4, letterSpacing: 0.8 }}>{label}</div>
              <code style={{ fontSize: 10, color: 'var(--blue)', wordBreak: 'break-all' }}>{cmd}</code>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Signal Weights (Current)">
        <SignalWeights />
      </Panel>
    </div>
  )
}

function SignalWeights() {
  const { data: w } = useQuery({ queryKey: ['weights'], queryFn: api.signalWeights })
  if (!w) return <EmptyState msg="No weight data" />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Object.entries(w).map(([name, weight]) => {
        const pct = (weight as number) * 100
        return (
          <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ minWidth: 130, fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {name.replace(/_/g, ' ')}
            </div>
            <div style={{ flex: 1, height: 3, background: 'var(--border)' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: 'var(--green)', transition: 'width 0.4s' }} />
            </div>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--green)', minWidth: 36, textAlign: 'right' }}>
              {pct.toFixed(0)}%
            </div>
          </div>
        )
      })}
    </div>
  )
}
