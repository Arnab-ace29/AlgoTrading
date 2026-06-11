import { useState } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LayoutDashboard, Radio, BarChart2, TrendingUp,
  FlaskConical, Shield, ShieldOff, Activity, Cpu,
  FlaskRound, KeyRound, X, ExternalLink, ListChecks, Pause, Play, Lock, LockOpen, LineChart, Clapperboard,
} from 'lucide-react'
import { api, getToken, setToken } from './api'
import { Tip } from './components'
import Overview   from './pages/Overview'
import Signals    from './pages/Signals'
import Positions  from './pages/Positions'
import Trades     from './pages/Trades'
import Backtest   from './pages/Backtest'
import ActionReplay from './pages/ActionReplay'
import Analytics  from './pages/Analytics'
import Live       from './pages/Live'
import AIModels   from './pages/AIModels'
import Roadmap    from './pages/Roadmap'

const NAV = [
  { to: '/',          icon: LayoutDashboard, label: 'Overview',   tip: 'At-a-glance KPIs: equity curve, today’s P&L, win rate and recent activity.' },
  { to: '/live',      icon: Activity,        label: 'Live',       tip: 'Live ops console — current scan, open positions, runner status and the control plane (kill / pause).' },
  { to: '/signals',   icon: Radio,           label: 'Signals',    tip: 'Per-symbol ensemble scores and the weight each signal contributes; tune signal weights here.' },
  { to: '/positions', icon: TrendingUp,      label: 'Positions',  tip: 'Currently open positions with entry, stop-loss, target and live P&L.' },
  { to: '/trades',    icon: BarChart2,       label: 'Trades',     tip: 'Closed-trade log and performance history — gross vs net P&L, win rate, by-strategy breakdown.' },
  { to: '/analytics', icon: LineChart,       label: 'Analytics',  tip: 'Edge vs costs (gross/net/cost bps), R-multiple distribution, exit-reason breakdown, a what-if simulator, and data-health coverage.' },
  { to: '/backtest',  icon: FlaskConical,    label: 'Backtest',   tip: 'Run the strategy over historical candles (walk-forward) and review per-fold metrics + run history.' },
  { to: '/action-replay', icon: Clapperboard, label: 'Action Replay', tip: 'Relive a single historical trading day exactly as the live bot would have: pre-market universe pick, bar-by-bar scan, entries/exits, P&L breakdown and a playable timeline.' },
  { to: '/ai',        icon: Cpu,             label: 'AI Models',  tip: 'ML / RL model status — which models are loaded and their last training metrics.' },
  { to: '/roadmap',   icon: ListChecks,      label: 'Roadmap',    tip: 'What’s built, in progress and pending across the whole system, with dates.' },
]

// Plain-language explanations for the header controls (shown on hover).
const EXPLAIN = {
  risk:    'Risk profile (LOW / MEDIUM / HIGH). Controls lot cap, ATR stop/target multipliers, max trades/day, concurrent positions and daily-loss limit. Click to change — applies live and is saved to .env.',
  capital: 'Trading capital used for position sizing and risk limits (NOT the broker balance). Click to edit. The daily-loss limit is a % of this. Applies live + saved to .env.',
  broker:  'Actual funds in your Upstox account, fetched live via OpenAlgo. Shows “—” in paper/sandbox mode or when the broker isn’t connected.',
  session: 'Win rate across today’s closed trades (green ≥ 50%).',
  pnl:     'Net profit/loss booked today, after costs (STT, brokerage, slippage).',
  trades:  'Number of trades taken today.',
  mode:    'Upstox environment. SANDBOX = test endpoint; LIVE = real account (still paper until you disable PAPER). Click to switch.',
  token:   'Paste the Upstox OAuth callback URL (or raw token) to refresh your access token without editing .env by hand.',
  apikey:  'Dashboard API token sent as X-API-Key on every action. Required only when DASHBOARD_TOKEN is set on the server.',
  trading: 'Auto-trade master switch. Pause suppresses NEW entries; open positions keep being managed. Does not flatten.',
  kill:    'Emergency stop. Flattens all open positions and halts new entries immediately (reaches the live runner via the control plane).',
}

/* ── Sidebar ─────────────────────────────────────────────────── */
function Sidebar() {
  const { pathname } = useLocation()
  const { data: s } = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 5000 })
  const ks = s?.circuit_breaker?.kill_switch_active ?? false
  const paper = s?.paper_mode ?? true

  return (
    <aside className="t-panel" style={{
      width: 190, flexShrink: 0, height: '100%',
      display: 'flex', flexDirection: 'column',
      borderLeft: 'none', borderTop: 'none', borderBottom: 'none',
    }}>
      {/* Logo */}
      <div style={{ padding: '14px 14px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--green)', letterSpacing: 0.5 }}>
          ◈ ALGOTRADING
        </div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 3, letterSpacing: 1.5 }}>
          {ks ? '⊘ KILL SWITCH' : paper ? '◉ PAPER MODE' : '◉ LIVE MODE'}
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '8px 0' }}>
        {NAV.map(({ to, icon: Icon, label, tip }) => {
          const active = to === '/' ? pathname === '/' : pathname.startsWith(to)
          return (
            <NavLink key={to} to={to} style={{ display: 'block', textDecoration: 'none' }}>
              <Tip text={tip} pos="right">
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 9, width: '100%',
                  padding: '8px 14px',
                  borderLeft: active ? '2px solid var(--green)' : '2px solid transparent',
                  background: active ? 'rgba(0,232,123,0.06)' : 'transparent',
                  color: active ? 'var(--green)' : 'var(--text-muted)',
                  cursor: 'pointer', transition: 'all 0.1s',
                  fontSize: 11, fontWeight: active ? 600 : 400,
                  textTransform: 'uppercase', letterSpacing: 0.5, boxSizing: 'border-box',
                }}>
                  <Icon size={13} />
                  {label}
                </div>
              </Tip>
            </NavLink>
          )
        })}
      </nav>

      {/* API status */}
      <ApiStatusFooter />
    </aside>
  )
}

function ApiStatusFooter() {
  const { isSuccess } = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 1, refetchInterval: 15000 })
  return (
    <div style={{
      padding: '8px 14px', borderTop: '1px solid var(--border)',
      display: 'flex', alignItems: 'center', gap: 6, fontSize: 9,
    }}>
      <span className={isSuccess ? 't-pulse' : ''} style={{
        display: 'inline-block', width: 5, height: 5,
        background: isSuccess ? 'var(--green)' : 'var(--red)',
      }} />
      <span style={{ color: isSuccess ? 'var(--green)' : 'var(--red)', letterSpacing: 1 }}>
        {isSuccess ? 'API ONLINE' : 'API OFFLINE'}
      </span>
    </div>
  )
}

/* ── Top bar ─────────────────────────────────────────────────── */
function Topbar() {
  const qc = useQueryClient()
  const { data: s } = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 5000 })
  const pnl      = s?.today_pnl ?? 0
  const ksActive = s?.circuit_breaker?.kill_switch_active ?? false
  const upstoxMode  = s?.upstox_mode ?? 'sandbox'
  const isPaper     = s?.paper_mode ?? true

  // Mode toggle mutation
  const modeMut = useMutation({
    mutationFn: ({ mode, paper }: { mode: 'sandbox' | 'live'; paper: boolean }) =>
      api.setMode(mode, paper),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })

  // Token modal state
  const [tokenModal, setTokenModal] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [tokenType, setTokenType]   = useState<'live' | 'sandbox'>('live')
  const [tokenMsg, setTokenMsg]     = useState('')

  const tokenMut = useMutation({
    mutationFn: () => api.updateToken(tokenInput, tokenType),
    onSuccess: (r) => { setTokenMsg(`✓ ${r.message} — preview: ${r.token_preview}`); setTokenInput('') },
    onError:   (e: Error) => setTokenMsg(`✗ ${e.message}`),
  })

  const handleModeToggle = () => {
    if (upstoxMode === 'sandbox') {
      modeMut.mutate({ mode: 'live', paper: true })
    } else {
      modeMut.mutate({ mode: 'sandbox', paper: true })
    }
  }

  // Auth URL — fetched from backend so the correct API key is embedded
  const authUrlQ = useQuery({
    queryKey: ['authUrl', tokenType],
    queryFn:  () => api.getAuthUrl(tokenType),
    enabled:  tokenModal && tokenType === 'live',
    staleTime: 60_000,
  })
  const upstoxAuthUrl = authUrlQ.data?.auth_url ?? ''

  return (
    <>
      <header style={{
        height: 38, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 16px', flexShrink: 0,
        borderBottom: '1px solid var(--border)', background: 'var(--panel-alt)',
      }}>
        {/* Left */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <RiskControl profile={s?.risk_profile ?? '—'} />
          <Sep />
          <CapitalControl capital={s?.capital ?? 0} />
          <BrokerFunds />
          <Sep />
          <TBar label="SESSION" value={`${((s?.today_win_rate ?? 0) * 100).toFixed(0)}% WR`}
            color={(s?.today_win_rate ?? 0) >= 0.5 ? 'var(--green)' : 'var(--red)'} tip={EXPLAIN.session} />
        </div>

        {/* Right */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TBar label="TODAY P&L"
            value={`${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(0)}`}
            color={pnl >= 0 ? 'var(--green)' : 'var(--red)'}
            glow tip={EXPLAIN.pnl} />
          <TBar label="TRADES" value={String(s?.today_trades ?? 0)} tip={EXPLAIN.trades} />
          <Sep />

          {/* Sandbox / Live mode toggle */}
          <Tip text={EXPLAIN.mode}>
            <button
              onClick={handleModeToggle}
              disabled={modeMut.isPending}
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                padding: '4px 10px', cursor: 'pointer',
                fontSize: 10, fontWeight: 700, letterSpacing: 0.6,
                fontFamily: "'JetBrains Mono', monospace",
                background: upstoxMode === 'sandbox'
                  ? 'rgba(232,195,0,0.12)' : 'rgba(77,166,255,0.12)',
                color: upstoxMode === 'sandbox' ? 'var(--yellow)' : 'var(--blue)',
                border: `1px solid ${upstoxMode === 'sandbox' ? 'rgba(232,195,0,0.3)' : 'rgba(77,166,255,0.3)'}`,
              }}>
              <FlaskRound size={10} />
              {upstoxMode === 'sandbox' ? 'SANDBOX' : 'LIVE'}{isPaper ? ' · PAPER' : ''}
            </button>
          </Tip>

          {/* Token update button */}
          <Tip text={EXPLAIN.token}>
            <button
              onClick={() => { setTokenModal(true); setTokenMsg('') }}
              className="t-btn"
              style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <KeyRound size={10} />
              TOKEN
            </button>
          </Tip>

          <Tip text={EXPLAIN.apikey}><ApiKeyBtn authEnabled={s?.auth_enabled ?? false} /></Tip>
          <Tip text={EXPLAIN.trading}><TradingToggle enabled={s?.trading_enabled ?? true} /></Tip>
          <Sep />
          <Tip text={EXPLAIN.kill}><KillSwitchBtn active={ksActive} /></Tip>
        </div>
      </header>

      {/* Token update modal */}
      {tokenModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setTokenModal(false)}>
          <div className="t-panel" style={{ width: 520, padding: 0 }}
            onClick={e => e.stopPropagation()}>

            {/* Modal header */}
            <div className="t-section-head" style={{ borderLeft: '2px solid var(--blue)' }}>
              <span style={{ color: 'var(--blue)' }}>
                <KeyRound size={11} style={{ display: 'inline', marginRight: 6 }} />
                UPDATE ACCESS TOKEN
              </span>
              <button onClick={() => setTokenModal(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', padding: 0 }}>
                <X size={13} />
              </button>
            </div>

            <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* Token type selector */}
              <div>
                <div className="t-label" style={{ marginBottom: 6 }}>Token Type</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {(['live', 'sandbox'] as const).map(t => (
                    <button key={t} onClick={() => setTokenType(t)}
                      className={tokenType === t ? 't-btn t-btn-blue' : 't-btn'}
                      style={{ flex: 1, textAlign: 'center' }}>
                      {t.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              {/* Auth link */}
              {tokenType === 'live' && (
                <div style={{
                  padding: '10px 12px', background: 'var(--bg)',
                  border: '1px solid var(--border)', fontSize: 10, color: 'var(--text-dim)',
                }}>
                  <div style={{ marginBottom: 6 }}>
                    Step 1 — click below to open Upstox login and authorize the app:
                  </div>
                  {authUrlQ.isLoading && (
                    <span style={{ color: 'var(--text-dim)' }}>Loading auth URL…</span>
                  )}
                  {authUrlQ.isError && (
                    <span style={{ color: 'var(--red)' }}>
                      {(authUrlQ.error as Error).message}
                    </span>
                  )}
                  {upstoxAuthUrl && (
                    <a href={upstoxAuthUrl} target="_blank" rel="noreferrer"
                      style={{
                        color: 'var(--blue)', display: 'flex', alignItems: 'center', gap: 5,
                        fontSize: 10, fontWeight: 700, textDecoration: 'none',
                      }}>
                      <ExternalLink size={10} />
                      OPEN UPSTOX LOGIN PAGE
                    </a>
                  )}
                  <div style={{ marginTop: 8, color: 'var(--text-muted)' }}>
                    Step 2 — after login, Upstox redirects to a URL like:<br />
                    <code style={{ color: 'var(--green)', fontSize: 9 }}>
                      http://127.0.0.1?code=xxxxxxxx
                    </code><br />
                    Copy that full URL (or just the token/code) and paste below.
                  </div>
                </div>
              )}

              {/* Token input */}
              <div>
                <div className="t-label" style={{ marginBottom: 6 }}>
                  Paste callback URL or raw token
                </div>
                <textarea
                  value={tokenInput}
                  onChange={e => setTokenInput(e.target.value)}
                  placeholder="http://127.0.0.1?code=xxxxxxxx  or  raw_token_string"
                  style={{
                    width: '100%', height: 72, resize: 'none',
                    background: 'var(--bg)', border: '1px solid var(--border)',
                    color: 'var(--text)', fontSize: 11, padding: '8px 10px',
                    fontFamily: "'JetBrains Mono', monospace", outline: 'none',
                  }}
                  onFocus={e => (e.target.style.borderColor = 'var(--green)')}
                  onBlur={e => (e.target.style.borderColor = 'var(--border)')}
                />
              </div>

              {/* Result message */}
              {tokenMsg && (
                <div style={{
                  fontSize: 10, padding: '7px 10px',
                  background: tokenMsg.startsWith('✓') ? 'var(--green-dim)' : 'var(--red-dim)',
                  border: `1px solid ${tokenMsg.startsWith('✓') ? '#1a4a2e' : '#4a1a1a'}`,
                  color: tokenMsg.startsWith('✓') ? 'var(--green)' : 'var(--red)',
                }}>
                  {tokenMsg}
                </div>
              )}

              {/* Submit */}
              <button
                onClick={() => tokenMut.mutate()}
                disabled={!tokenInput.trim() || tokenMut.isPending}
                className="t-btn t-btn-green"
                style={{ width: '100%', textAlign: 'center', padding: '9px 0', opacity: !tokenInput.trim() ? 0.4 : 1 }}>
                {tokenMut.isPending ? 'SAVING…' : 'SAVE TOKEN TO .ENV'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function TBar({ label, value, color, glow, tip }: { label: string; value: string; color?: string; glow?: boolean; tip?: string }) {
  const inner = (
    <div style={{ lineHeight: 1 }}>
      <div style={{ fontSize: 8, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 2 }}>{label}</div>
      <div style={{
        fontSize: 11, fontWeight: 700, color: color ?? 'var(--text)',
        textShadow: glow && color ? `0 0 8px ${color}55` : undefined,
      }}>{value}</div>
    </div>
  )
  return tip ? <Tip text={tip}>{inner}</Tip> : inner
}

/* Editable risk-profile selector (LOW / MEDIUM / HIGH) in the header. */
function RiskControl({ profile }: { profile: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const mut = useMutation({
    mutationFn: (p: 'LOW' | 'MEDIUM' | 'HIGH') => api.setRisk(p),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ['status'] }) },
  })
  const colors: Record<string, string> = { LOW: 'var(--green)', MEDIUM: 'var(--yellow)', HIGH: 'var(--red)' }
  return (
    <div style={{ position: 'relative' }}>
      <Tip text={EXPLAIN.risk}>
        <button onClick={() => setOpen(o => !o)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left', lineHeight: 1 }}>
          <div style={{ fontSize: 8, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 2 }}>RISK ▾</div>
          <div style={{ fontSize: 11, fontWeight: 700, color: colors[profile] ?? 'var(--text)', display: 'flex', alignItems: 'center', gap: 3 }}>
            {profile || '—'}
          </div>
        </button>
      </Tip>
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 2900 }} />
          <div className="t-panel" style={{ position: 'absolute', top: '100%', left: 0, marginTop: 6, zIndex: 3000, minWidth: 96 }}>
            {(['LOW', 'MEDIUM', 'HIGH'] as const).map(p => (
              <div key={p} onClick={() => mut.mutate(p)} style={{
                padding: '7px 11px', fontSize: 10, fontWeight: 700, cursor: 'pointer',
                color: colors[p], letterSpacing: 0.5,
                background: p === profile ? 'var(--panel-alt)' : 'transparent',
              }}>{p}{p === profile ? ' ✓' : ''}</div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* Editable trading-capital (used for sizing/risk, not broker balance). */
function CapitalControl({ capital }: { capital: number }) {
  const qc = useQueryClient()
  const mut = useMutation({
    mutationFn: (v: number) => api.setCapital(v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })
  const edit = () => {
    const inp = window.prompt('Trading capital in ₹ (used for sizing & risk limits — not your broker balance):', String(Math.round(capital)))
    if (inp == null) return
    const v = Number(inp.replace(/[,\s₹]/g, ''))
    if (!Number.isFinite(v) || v <= 0) { window.alert('Enter a positive number, e.g. 100000'); return }
    mut.mutate(v)
  }
  return (
    <Tip text={EXPLAIN.capital}>
      <button onClick={edit}
        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, textAlign: 'left', lineHeight: 1 }}>
        <div style={{ fontSize: 8, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 2 }}>CAPITAL ✎</div>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text)' }}>₹{(capital / 100000).toFixed(1)}L</div>
      </button>
    </Tip>
  )
}

/* Actual broker funds from Upstox (via OpenAlgo). */
function BrokerFunds() {
  const { data: f } = useQuery({ queryKey: ['funds'], queryFn: api.funds, refetchInterval: 30000, retry: 1 })
  const val = f?.ok && f.available != null ? `₹${(f.available / 100000).toFixed(2)}L` : '—'
  const tip = f && !f.ok && f.reason ? `${EXPLAIN.broker}  —  ${f.reason}.` : EXPLAIN.broker
  return <TBar label="BROKER" value={val} color={f?.ok ? 'var(--blue)' : undefined} tip={tip} />
}

function Sep() {
  return <div style={{ width: 1, height: 18, background: 'var(--border)' }} />
}

function ApiKeyBtn({ authEnabled }: { authEnabled: boolean }) {
  const [hasToken, setHasToken] = useState(!!getToken())
  const edit = () => {
    const t = window.prompt('Dashboard API token (sent as X-API-Key on actions):', getToken())
    if (t !== null) { setToken(t.trim()); setHasToken(!!t.trim()) }
  }
  // Server requires a token (authEnabled) but none is set locally → warn (red).
  const missing = authEnabled && !hasToken
  return (
    <button onClick={edit} className={missing ? 't-btn t-btn-red' : 't-btn'}
      title={authEnabled
        ? (hasToken ? 'API token set — click to change' : 'Server requires a token — click to set')
        : 'Auth disabled on server (localhost). Click to set a token anyway.'}
      style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      {hasToken ? <Lock size={10} /> : <LockOpen size={10} />}
      KEY
    </button>
  )
}

function TradingToggle({ enabled }: { enabled: boolean }) {
  const qc = useQueryClient()
  const mut = useMutation({
    mutationFn: () => api.setTrading(!enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })
  return (
    <button onClick={() => mut.mutate()} disabled={mut.isPending}
      title={enabled ? 'Pause new entries (positions still managed)' : 'Resume auto-trading'}
      className={enabled ? 't-btn t-btn-green' : 't-btn t-btn-yellow'}
      style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      {enabled ? <Play size={10} /> : <Pause size={10} />}
      {enabled ? 'AUTO' : 'PAUSED'}
    </button>
  )
}

function KillSwitchBtn({ active }: { active: boolean }) {
  const qc = useQueryClient()
  const mut = useMutation({
    mutationFn: () => api.killSwitch(!active),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['status'] }),
  })
  const toggle = () => {
    if (!active && !window.confirm('Activate KILL SWITCH? This flattens all open positions and halts new entries.')) return
    mut.mutate()
  }
  return (
    <button onClick={toggle} disabled={mut.isPending} className={active ? 't-btn t-btn-red' : 't-btn'}
      style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      {active ? <ShieldOff size={10} /> : <Shield size={10} />}
      {active ? 'DEACTIVATE' : 'KILL SWITCH'}
    </button>
  )
}

/* ── Root layout ─────────────────────────────────────────────── */
export default function App() {
  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--bg)', overflow: 'hidden' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Topbar />
        <main style={{ flex: 1, overflowY: 'auto', padding: '16px 18px' }} className="fadein">
          <Routes>
            <Route path="/"          element={<Overview />} />
            <Route path="/live"      element={<Live />} />
            <Route path="/signals"   element={<Signals />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/trades"    element={<Trades />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/backtest"  element={<Backtest />} />
            <Route path="/action-replay" element={<ActionReplay />} />
            <Route path="/ai"        element={<AIModels />} />
            <Route path="/roadmap"   element={<Roadmap />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
