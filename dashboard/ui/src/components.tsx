/* ── Shared retro terminal UI components ──────────────────── */

import { useState } from 'react'

/**
 * Hover explanation. Wrap any element; on hover it shows a small styled tooltip
 * describing what the thing does. `pos` controls which side it pops out on
 * (default 'bottom' — use 'right' for sidebar items, 'top' near the page bottom).
 */
export function Tip({ text, pos = 'bottom', children }: {
  text: string; pos?: 'bottom' | 'top' | 'right'; children: React.ReactNode
}) {
  const [show, setShow] = useState(false)
  const place: React.CSSProperties =
    pos === 'right' ? { left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: 8 }
    : pos === 'top' ? { bottom: '100%', left: 0, marginBottom: 6 }
    : { top: '100%', left: 0, marginTop: 6 }
  return (
    <span
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span role="tooltip" style={{
          position: 'absolute', ...place, zIndex: 3000,
          background: 'var(--panel-alt)', border: '1px solid var(--border-hi)',
          color: 'var(--text)', fontSize: 10, fontWeight: 400, lineHeight: 1.5,
          letterSpacing: 0, textTransform: 'none', textAlign: 'left',
          padding: '7px 10px', width: 'max-content', maxWidth: 250,
          boxShadow: '0 6px 24px rgba(0,0,0,0.55)', pointerEvents: 'none',
          fontFamily: "'JetBrains Mono', monospace", whiteSpace: 'normal',
        }}>{text}</span>
      )}
    </span>
  )
}

export function Panel({ title, right, children, accent }: {
  title?: string; right?: React.ReactNode; children: React.ReactNode; accent?: string
}) {
  return (
    <div className="t-panel" style={{ overflow: 'hidden' }}>
      {title && (
        <div className="t-section-head" style={accent ? { borderLeft: `2px solid ${accent}` } : {}}>
          <span style={accent ? { color: accent } : {}}>{title}</span>
          {right && <span>{right}</span>}
        </div>
      )}
      <div style={{ padding: '12px 14px' }}>{children}</div>
    </div>
  )
}

export function KpiCard({ label, value, sub, color, glow }: {
  label: string; value: string; sub?: string; color?: string; glow?: boolean
}) {
  return (
    <div className="t-panel" style={{ padding: '12px 14px' }}>
      <div className="t-label" style={{ marginBottom: 6 }}>{label}</div>
      <div style={{
        fontSize: 20, fontWeight: 700, color: color ?? 'var(--text)',
        textShadow: glow && color ? `0 0 12px ${color}66` : undefined,
        lineHeight: 1,
      }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 5 }}>{sub}</div>}
    </div>
  )
}

export function Badge({ text, variant = 'neutral' }: {
  text: string
  variant?: 'green' | 'red' | 'blue' | 'yellow' | 'neutral'
}) {
  const v = {
    green:   { background: 'var(--green-dim)', color: 'var(--green)', border: '1px solid #1a4a2e' },
    red:     { background: 'var(--red-dim)',   color: 'var(--red)',   border: '1px solid #4a1a1a' },
    blue:    { background: 'var(--blue-dim)',  color: 'var(--blue)',  border: '1px solid #1a2e4a' },
    yellow:  { background: '#1a1a00',          color: 'var(--yellow)',border: '1px solid #3a3a00' },
    neutral: { background: 'transparent',      color: 'var(--text-dim)', border: '1px solid var(--border)' },
  }[variant]
  return (
    <span style={{ ...v, fontSize: 9, fontWeight: 700, padding: '2px 6px', letterSpacing: 0.5, textTransform: 'uppercase' }}>
      {text}
    </span>
  )
}

export function Spinner() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '32px 0' }}>
      <div style={{
        width: 16, height: 16,
        border: '2px solid var(--border)', borderTopColor: 'var(--green)',
        animation: 'spin 0.6s linear infinite',
      }} />
    </div>
  )
}

export function EmptyState({ msg }: { msg: string }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', padding: '36px 0', gap: 8,
    }}>
      <span style={{ fontSize: 18, color: 'var(--border-hi)' }}>◌</span>
      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1 }}>{msg}</span>
    </div>
  )
}

export function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(Math.abs(score) * 100, 100)
  const color = score > 0.05 ? 'var(--green)' : score < -0.05 ? 'var(--red)' : 'var(--border-hi)'
  const textColor = score > 0.05 ? 'var(--green)' : score < -0.05 ? 'var(--red)' : 'var(--text-dim)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontFamily: 'inherit', fontSize: 11, color: textColor, minWidth: 54 }}>
        {score > 0 ? '+' : ''}{score.toFixed(3)}
      </span>
      <div style={{ width: 56, height: 2, background: 'var(--border)' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width 0.3s' }} />
      </div>
    </div>
  )
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, color: 'var(--green)',
      textTransform: 'uppercase', letterSpacing: 1.5,
      marginBottom: 14, display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <span style={{ color: 'var(--text-muted)' }}>▸</span>
      {children}
    </div>
  )
}

/* CHART_STYLE moved to ./theme to keep this file component-only (fast refresh). */
