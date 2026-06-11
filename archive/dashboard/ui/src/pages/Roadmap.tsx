import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Check, Loader, Circle, Trash2, X } from 'lucide-react'
import { api } from '../api'
import type { Feature, FeatureStatus, NewFeature } from '../api'
import { Panel, KpiCard, Badge, Spinner, EmptyState, SectionTitle } from '../components'

const COLUMNS: { key: FeatureStatus; label: string; color: string }[] = [
  { key: 'pending',     label: 'Pending',     color: 'var(--text-muted)' },
  { key: 'in_progress', label: 'In Progress', color: 'var(--yellow)' },
  { key: 'done',        label: 'Done',        color: 'var(--green)' },
]

const CATEGORIES = ['Execution', 'Risk', 'Signals', 'ML/RL', 'Backtest', 'Data', 'Dashboard', 'Screener', 'Compliance', 'Other']

function priorityVariant(p: string): 'red' | 'yellow' | 'blue' | 'neutral' {
  if (p === 'P0') return 'red'
  if (p === 'P1') return 'yellow'
  if (p === 'P2') return 'blue'
  return 'neutral'
}

export default function Roadmap() {
  const qc = useQueryClient()
  const { data: features, isLoading } = useQuery({ queryKey: ['features'], queryFn: api.features })
  const { data: stats } = useQuery({ queryKey: ['feature-stats'], queryFn: api.featureStats })

  const [catFilter, setCatFilter] = useState<string>('ALL')
  const [showAdd, setShowAdd] = useState(false)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['features'] })
    qc.invalidateQueries({ queryKey: ['feature-stats'] })
  }

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: FeatureStatus }) => api.updateFeature(id, { status }),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteFeature(id),
    onSuccess: invalidate,
  })
  const add = useMutation({
    mutationFn: (f: NewFeature) => api.addFeature(f),
    onSuccess: () => { invalidate(); setShowAdd(false) },
  })

  const categories = useMemo(() => {
    const set = new Set<string>((features ?? []).map(f => f.category))
    return ['ALL', ...Array.from(set).sort()]
  }, [features])

  const filtered = (features ?? []).filter(f => catFilter === 'ALL' || f.category === catFilter)
  const pct = stats?.pct_complete ?? 0

  if (isLoading) return <Spinner />

  return (
    <div className="fadein" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <SectionTitle>Roadmap &amp; Feature Tracker</SectionTitle>
        <button className="t-btn t-btn-green" style={{ display: 'flex', alignItems: 'center', gap: 5 }}
          onClick={() => setShowAdd(v => !v)}>
          {showAdd ? <X size={11} /> : <Plus size={11} />}
          {showAdd ? 'CLOSE' : 'ADD FEATURE'}
        </button>
      </div>

      {/* Progress KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <Panel title="OVERALL PROGRESS">
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--green)', lineHeight: 1 }}>{pct.toFixed(0)}%</div>
          <div style={{ height: 4, background: 'var(--border)', marginTop: 8 }}>
            <div style={{ width: `${pct}%`, height: '100%', background: 'var(--green)', transition: 'width 0.4s' }} />
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 6 }}>
            {stats?.by_status.done ?? 0} of {stats?.total ?? 0} shipped
          </div>
        </Panel>
        <KpiCard label="Done"        value={String(stats?.by_status.done ?? 0)}        color="var(--green)" />
        <KpiCard label="In Progress" value={String(stats?.by_status.in_progress ?? 0)} color="var(--yellow)" />
        <KpiCard label="Pending"     value={String(stats?.by_status.pending ?? 0)}     color="var(--text-dim)" />
      </div>

      {/* Add form */}
      {showAdd && <AddFeatureForm onAdd={f => add.mutate(f)} pending={add.isPending} />}

      {/* Category filter */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {categories.map(c => (
          <button key={c} onClick={() => setCatFilter(c)}
            className={catFilter === c ? 't-btn t-btn-blue' : 't-btn'}
            style={{ fontSize: 9 }}>
            {c}
          </button>
        ))}
      </div>

      {/* Kanban board */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, alignItems: 'start' }}>
        {COLUMNS.map(col => {
          const items = filtered.filter(f => f.status === col.key)
          return (
            <Panel key={col.key} title={`${col.label} (${items.length})`} accent={col.color}>
              {items.length === 0
                ? <EmptyState msg="Nothing here" />
                : <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {items.map(f => (
                      <FeatureCard key={f.id} f={f}
                        onSetStatus={(status) => setStatus.mutate({ id: f.id, status })}
                        onDelete={() => remove.mutate(f.id)} />
                    ))}
                  </div>}
            </Panel>
          )
        })}
      </div>
    </div>
  )
}

function FeatureCard({ f, onSetStatus, onDelete }: {
  f: Feature
  onSetStatus: (s: FeatureStatus) => void
  onDelete: () => void
}) {
  return (
    <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', padding: '9px 10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', lineHeight: 1.35 }}>{f.title}</span>
        <button onClick={onDelete} title="Delete"
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', padding: 0, flexShrink: 0 }}>
          <Trash2 size={11} />
        </button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
        <Badge text={f.category} variant="neutral" />
        {f.priority && <Badge text={f.priority} variant={priorityVariant(f.priority)} />}
        {f.phase && <Badge text={`P${f.phase}`} variant="neutral" />}
        {f.issue_ref && <Badge text={f.issue_ref} variant="blue" />}
      </div>

      {f.notes && (
        <div style={{ fontSize: 9.5, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.4 }}>{f.notes}</div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          <StatusBtn icon={<Circle size={10} />}  active={f.status === 'pending'}     onClick={() => onSetStatus('pending')}     title="Pending" />
          <StatusBtn icon={<Loader size={10} />}  active={f.status === 'in_progress'} onClick={() => onSetStatus('in_progress')} title="In progress" />
          <StatusBtn icon={<Check size={10} />}   active={f.status === 'done'}        onClick={() => onSetStatus('done')}        title="Done" />
        </div>
        <span style={{ fontSize: 8.5, color: 'var(--text-muted)', letterSpacing: 0.5 }}>
          {f.status === 'done' && f.completed_at ? `✓ ${f.completed_at}` : `added ${f.added_at}`}
        </span>
      </div>
    </div>
  )
}

function StatusBtn({ icon, active, onClick, title }: {
  icon: React.ReactNode; active: boolean; onClick: () => void; title: string
}) {
  return (
    <button onClick={onClick} title={title}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        width: 22, height: 18, cursor: 'pointer',
        background: active ? 'rgba(0,232,123,0.12)' : 'transparent',
        border: `1px solid ${active ? 'var(--green)' : 'var(--border)'}`,
        color: active ? 'var(--green)' : 'var(--text-muted)',
      }}>
      {icon}
    </button>
  )
}

function AddFeatureForm({ onAdd, pending }: { onAdd: (f: NewFeature) => void; pending: boolean }) {
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('Signals')
  const [status, setStatus] = useState<FeatureStatus>('pending')
  const [priority, setPriority] = useState('')
  const [notes, setNotes] = useState('')

  const submit = () => {
    if (!title.trim()) return
    onAdd({ title: title.trim(), category, status, priority, notes: notes.trim() })
    setTitle(''); setNotes(''); setPriority('')
  }

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)',
    fontSize: 11, padding: '7px 9px', fontFamily: "'JetBrains Mono', monospace", outline: 'none',
  }

  return (
    <Panel title="Add Feature" accent="var(--green)">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <input style={inputStyle} placeholder="Feature title…" value={title}
          onChange={e => setTitle(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') submit() }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          <select style={inputStyle} value={category} onChange={e => setCategory(e.target.value)}>
            {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select style={inputStyle} value={status} onChange={e => setStatus(e.target.value as FeatureStatus)}>
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
          </select>
          <select style={inputStyle} value={priority} onChange={e => setPriority(e.target.value)}>
            <option value="">No priority</option>
            <option value="P0">P0</option>
            <option value="P1">P1</option>
            <option value="P2">P2</option>
          </select>
        </div>
        <input style={inputStyle} placeholder="Notes (optional)" value={notes} onChange={e => setNotes(e.target.value)} />
        <button className="t-btn t-btn-green" disabled={!title.trim() || pending}
          style={{ padding: '8px 0', opacity: !title.trim() ? 0.4 : 1 }} onClick={submit}>
          {pending ? 'ADDING…' : 'ADD TO BOARD'}
        </button>
      </div>
    </Panel>
  )
}
