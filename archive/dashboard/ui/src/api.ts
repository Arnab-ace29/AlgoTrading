const BASE = '/api'
const TOKEN_KEY = 'algo_api_token'

// Dashboard API token (SEC-01). Stored in localStorage and sent as X-API-Key on
// mutating requests; required by the server only when DASHBOARD_TOKEN is set.
export function getToken(): string { return localStorage.getItem(TOKEN_KEY) || '' }
export function setToken(t: string): void {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}
function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { 'X-API-Key': t } : {}
}
function err(r: Response): Error {
  if (r.status === 401) return new Error('401 Unauthorized — set the dashboard API token (lock icon)')
  return new Error(`${r.status} ${r.statusText}`)
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { headers: authHeaders() })
  if (!r.ok) throw err(r)
  return r.json()
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw err(r)
  return r.json()
}
const post  = <T>(path: string, body?: unknown) => send<T>('POST', path, body)
const patch = <T>(path: string, body?: unknown) => send<T>('PATCH', path, body)
const del   = <T>(path: string) => send<T>('DELETE', path)

export const api = {
  health:             () => get<{ status: string }>('/health'),
  status:             () => get<SystemStatus>('/system/status'),
  killSwitch:         (active: boolean) => post<{ kill_switch: boolean; message: string }>('/system/kill-switch', { active }),
  getTrading:         () => get<{ trading_enabled: boolean }>('/system/trading'),
  setTrading:         (enabled: boolean) => post<{ trading_enabled: boolean; message: string }>('/system/trading', { enabled }),
  control:            () => get<ControlState>('/system/control'),
  setRisk:            (profile: 'LOW' | 'MEDIUM' | 'HIGH') => post<{ risk_profile: string; message: string }>('/system/risk', { profile }),
  setCapital:         (capital: number) => post<{ capital: number; message: string }>('/system/capital', { capital }),
  funds:              () => get<Funds>('/system/funds'),
  setMode:            (mode: 'sandbox' | 'live', paper_trade: boolean) => post<{ upstox_mode: string; paper_mode: boolean; message: string }>('/system/mode', { mode, paper_trade }),
  updateToken:        (callback_url: string, token_type: 'live' | 'sandbox') => post<{ env_key: string; token_preview: string; message: string }>('/system/token', { callback_url, token_type }),
  getAuthUrl:         (token_type: 'live' | 'sandbox') => get<{ auth_url: string; redirect_uri: string }>(`/system/auth-url?token_type=${token_type}`),

  signalScan:         (symbols?: string) => get<SignalResult[]>(`/signals/scan${symbols ? `?symbols=${symbols}` : ''}`),
  signalWeights:      () => get<Record<string, number>>('/signals/weights'),
  updateWeights:      (weights: Record<string, number>) => post('/signals/weights', { weights }),
  toggleSignal:       (signal_name: string, enabled: boolean) => post('/signals/toggle', { signal_name, enabled }),

  trades:             (limit = 100) => get<Trade[]>(`/trades/?limit=${limit}`),
  equityCurve:        (days = 90) => get<EquityPoint[]>(`/trades/equity-curve?days=${days}`),
  dailyStats:         () => get<DailyStats>('/trades/daily-stats'),
  performanceHistory: (days = 30) => get<PerfRow[]>(`/trades/performance-history?days=${days}`),
  byStrategy:         () => get<StrategyRow[]>('/trades/by-strategy'),

  openPositions:      () => get<Position[]>('/positions/open'),

  runBacktest:        (req: BacktestRequest) => post<{ message: string }>('/backtest/run', req),
  backtestResult:     () => get<BacktestResult | { message: string }>('/backtest/results'),
  backtestHistory:    () => get<BacktestRun[]>('/backtest/history'),

  modelStatus:        () => get<ModelStatus>('/models/status'),

  // Action Replay (full-fidelity single-day live simulation)
  runReplay:          (req: ReplayRunReq) => post<{ message: string }>('/replay/run', req),
  replayStatus:       () => get<ReplayStatus>('/replay/status'),
  replayResult:       () => get<ReplayResult | { message: string }>('/replay/result'),
  replayHistory:      () => get<ReplayHistoryRow[]>('/replay/history'),

  // Analytics (DASH-02..05)
  analyticsSummary:   (days = 90, mode?: string) => get<AnalyticsSummary>(`/analytics/summary?days=${days}${mode ? `&mode=${mode}` : ''}`),
  rMultiples:         (days = 90, mode?: string) => get<RMultiple[]>(`/analytics/r-multiples?days=${days}${mode ? `&mode=${mode}` : ''}`),
  byExitReason:       (days = 90, mode?: string) => get<ExitReasonRow[]>(`/analytics/by-exit-reason?days=${days}${mode ? `&mode=${mode}` : ''}`),
  whatIf:             (p: WhatIfParams) => get<WhatIfResult>(
    `/analytics/whatif?days=${p.days ?? 9999}&cost_mult=${p.cost_mult ?? 1}&min_score=${p.min_score ?? 0}&only_target_exits=${p.only_target_exits ? 'true' : 'false'}${p.mode ? `&mode=${p.mode}` : ''}`),
  dataHealth:         () => get<DataHealth>('/analytics/data-health'),

  // Feature tracker / roadmap
  features:           () => get<Feature[]>('/features/'),
  featureStats:       () => get<FeatureStats>('/features/stats'),
  addFeature:         (f: NewFeature) => post<Feature>('/features/', f),
  updateFeature:      (id: string, upd: Partial<NewFeature>) => patch<Feature>(`/features/${id}`, upd),
  deleteFeature:      (id: string) => del<{ deleted: string }>(`/features/${id}`),
}

export interface CircuitBreakerStatus {
  kill_switch_active: boolean
  daily_loss_limit: number
  halted?: boolean
  halt_reason?: string
  trades_today?: number
  max_trades?: number
  in_blackout?: boolean
  blackout_reason?: string
}

export interface SystemStatus {
  timestamp: string
  upstox_mode: 'sandbox' | 'live'
  paper_mode: boolean
  risk_profile: string
  capital: number
  auth_enabled: boolean
  trading_enabled: boolean
  circuit_breaker: CircuitBreakerStatus
  today_pnl: number
  today_gross_pnl: number
  today_costs: number
  today_trades: number
  today_win_rate: number
  control_updated?: string
}

export interface ControlState {
  kill_switch: boolean
  trading_enabled: boolean
  weights_override: Record<string, number>
  disabled_signals: string[]
  risk_profile: string | null
  capital: number | null
  updated_at: string | null
}

export interface Funds {
  ok: boolean
  available: number | null
  used: number | null
  total: number | null
  reason?: string
}

export interface SignalResult {
  symbol: string
  composite_score: number
  direction: 'LONG' | 'SHORT' | 'NEUTRAL'
  regime: string
  signal_scores: Record<string, number>
  weights_used: Record<string, number>
  actionable: boolean
}

export interface Trade {
  trade_id: string
  symbol: string
  side: string
  qty: number
  entry_price: number
  exit_price: number
  pnl: number
  pnl_pct: number
  entry_time: string
  exit_time: string
  strategy: string
  status: string
  regime_at_entry?: string
  exit_reason?: string
  sl_price?: number
  target_price?: number
  entry_score?: number
}

export interface EquityPoint { date: string; equity: number; net_pnl: number }
export interface DailyStats {
  gross_pnl: number; net_pnl: number; total_costs: number; total_trades: number
  wins: number; losses: number; win_rate: number
}
export interface PerfRow { date: string; gross_pnl: number; net_pnl: number; total_trades: number; win_rate: number }
export interface StrategyRow { strategy: string; total_trades: number; wins: number; win_rate: number; total_pnl: number; avg_pnl: number }
export interface Position {
  trade_id: string; symbol: string; side: string; qty: number
  entry_price: number; sl_price: number; target_price: number
  entry_score?: number; regime_at_entry?: string; entry_time?: string; status?: string
}
export interface BacktestRequest { symbols: string[]; from_date: string; to_date: string; walk_forward: boolean; n_folds: number }
export interface BacktestResult { run_id?: string; total_return: number; sharpe: number; max_drawdown: number; win_rate: number; total_trades: number; avg_trade_pct: number }
export interface BacktestRun { run_id: string; run_time: string; total_return: number; sharpe: number; symbols?: string; win_rate?: number; total_trades?: number }

export interface ModelInfo {
  file: string; label: string; description: string; loaded: boolean
  size_kb: number; modified: string | null
}
export interface TrainingLogRow {
  run_id: string; run_time: string; model_name: string
  train_auc?: number; val_auc?: number; n_samples?: number; features_used?: number
}
export interface ModelStatus {
  models: ModelInfo[]; loaded_count: number; total_count: number
  training_log: TrainingLogRow[]; models_dir: string
}

export interface AnalyticsSummary {
  trades: number; wins: number; losses: number; win_rate: number
  gross_pnl: number; costs: number; net_pnl: number
  expectancy: number; profit_factor: number | null
  avg_win: number; avg_loss: number
  gross_bps: number | null; cost_bps: number | null
  avg_R: number | null; expectancy_R: number | null
  window_days?: number; mode?: string
}
export interface RMultiple {
  symbol: string; exit_reason?: string; net_pnl: number; risk: number
  R: number; entry_score?: number; exit_time?: string
}
export interface ExitReasonRow { exit_reason: string; trades: number; net_pnl: number; win_rate: number; avg_net: number }
export interface WhatIfParams { days?: number; mode?: string; cost_mult?: number; min_score?: number; only_target_exits?: boolean }
export interface WhatIfResult {
  baseline: AnalyticsSummary; scenario: AnalyticsSummary
  params: { cost_mult: number; min_score: number; only_target_exits: boolean; kept_trades?: number; dropped_trades?: number }
}
export interface DataHealthRow {
  symbol: string; timeframe: string; source: string; bars: number
  first_ts: string; last_ts: string; age_hours: number | null; is_demo: boolean
}
export interface DataHealth { rows: DataHealthRow[]; symbols: number; total_bars: number; now_utc: string }

export type FeatureStatus = 'done' | 'in_progress' | 'pending'
export interface Feature {
  id: string; title: string; category: string; status: FeatureStatus
  priority: string; phase: string; issue_ref: string; notes: string
  added_at: string; completed_at: string | null; updated_at: string
}
export interface NewFeature {
  title: string; category?: string; status?: FeatureStatus
  priority?: string; phase?: string; notes?: string; issue_ref?: string
}
export interface FeatureStats {
  total: number
  by_status: Record<FeatureStatus, number>
  by_category: Record<string, { done: number; in_progress: number; pending: number; total: number }>
  pct_complete: number
}

/* ── Action Replay ──────────────────────────────────────────── */
export interface ReplayRunReq {
  date: string
  capital?: number
  risk_profile?: 'LOW' | 'MEDIUM' | 'HIGH'
  use_ml_gates: boolean
  use_margin: boolean
}
export interface ReplayStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  progress: number
  message: string
  run_id: string | null
  date: string | null
}
export interface ReplayEvent {
  t: string
  type: string
  symbol: string
  detail: Record<string, unknown>
}
export interface ReplayTrade {
  symbol: string; side: string; direction: string; qty: number
  entry_time: string; exit_time: string
  entry_price: number; exit_price: number
  notional: number; leverage: number
  gross_pnl: number; cost: number; net_pnl: number; return_pct: number
  bars_held: number; exit_reason: string; entry_score: number
  regime: string; sizing_note: string
  cost_parts: Record<string, number>
  signal_scores: Record<string, number>
  margin_multiplier?: number
  margin_required?: number
}
export interface ReplayUniverseRow {
  symbol: string
  strategies: string[]
  screener_score: number | null
  reasons: string[]
  last_score: number | null
  direction: string | null
  regime: string | null
  status: string
  multiplier?: number | null
  margin_pct?: number | null
}
export interface ReplaySummary {
  total_trades: number; wins: number; losses: number; win_rate: number
  longs: number; shorts: number
  gross_pnl: number; costs: number; net_pnl: number; max_drawdown: number
  return_pct: number; profit_factor: number | null; expectancy: number
  capital: number; peak_exposure: number; peak_exposure_pct: number
  peak_leverage: number; uses_margin: boolean
  cost_parts: Record<string, number>
  by_exit_reason: Record<string, { trades: number; net: number }>
}
export interface ReplayResult {
  run_id: string
  date: string
  params: { capital: number; risk_profile: string; use_ml_gates: boolean; timeframe: string }
  summary: ReplaySummary
  universe: ReplayUniverseRow[]
  trades: ReplayTrade[]
  events: ReplayEvent[]
  gate_counts: Record<string, number>
  watchlist: Record<string, string[]>
}
export interface ReplayHistoryRow {
  run_id: string; date: string; summary: ReplaySummary
  params: Record<string, unknown>; file: string
}
