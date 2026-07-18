/** Shared TypeScript types matching the API response shapes. */

export type GameStatus = 'scheduled' | 'live' | 'final' | 'postponed'
export type SeasonType = 'regular' | 'play_in' | 'playoffs'
export type GameDataStatus = 'summary_only' | 'events_ready' | 'analysis_ready'

export interface GameSummary {
  id: number
  nba_game_id: string
  season: string
  game_date: string
  home_team_id: string
  away_team_id: string
  home_score: number
  away_score: number
  status: GameStatus
  season_type: SeasonType
  data_status: GameDataStatus
  source_name: string | null
  source_url: string | null
  source_game_id: string | null
  game_label: string | null
  series_name: string | null
  series_game_number: number | null
  margin: number
  winner_team_id: string
}

export interface GameDetail extends GameSummary {
  home_team: Team | null
  away_team: Team | null
}

export interface Team {
  id: string
  name: string
  city: string
  abbreviation: string
  conference?: string
  division?: string
  nba_team_id: number
}

export interface Player {
  id: number
  nba_player_id: number
  full_name: string
  team_id: string | null
  position: string | null
  jersey_number: string | null
}

export interface GameEvent {
  id: number
  game_id: number
  sequence: number
  period: number
  clock: string
  team_id: string | null
  player_id: number | null
  player_name: string | null
  event_type: string
  description: string
  home_score: number
  away_score: number
  score_margin: number
  shot_type: string | null
  shot_result: string | null
}

export interface ScoringRun {
  id: number
  game_id: number
  team_id: string
  period: number
  start_clock: string
  end_clock: string
  points_for: number
  points_against: number
  score_delta: number
  event_count: number
  summary: string
}

export interface BadStretch {
  id: number
  game_id: number
  period: number
  start_clock: string
  end_clock: string
  score_delta: number
  summary: string
  likely_causes: string[]
  knicks_turnovers: number
  knicks_missed_shots: number
  opponent_fast_breaks: number
}

export interface Report {
  id: number
  game_id: number
  title: string
  summary: string
  turning_point: string
  best_stretch: string
  worst_stretch: string
  player_notes: string[]
  suggested_adjustments: string[]
  sources: { type: string; [key: string]: unknown }[]
  tool_calls: { tool: string; latency_ms: number; [key: string]: unknown }[]
  created_at: string
}

export interface AnalysisCitation {
  claim: string
  type: string
  title: string
  game_id: number | null
  source_name: string | null
  source_url: string | null
  metadata: Record<string, unknown>
}

export interface AnalysisContextMessage {
  role: 'user' | 'assistant'
  content: string
}

export type AnalyticsResultType =
  | 'game_log'
  | 'aggregate'
  | 'period_comparison'
  | 'player_comparison'
  | 'split'
  | 'leaderboard'
  | 'streak'
  | 'trend'
  | 'outlier'
  | 'outcome_association'
  | 'notable_facts'

export interface AnalyticsTimeframe {
  kind: string
  label: string
  last_n?: number | null
  unit?: string
  start_date?: string | null
  end_date?: string | null
}

export interface AnalyticsResult {
  id: string
  type: AnalyticsResultType
  title: string
  raw_values: Record<string, number | null>
  display_values: Record<string, string>
  sample_size: number
  timeframe: AnalyticsTimeframe
  warnings: string[]
  source_game_ids: number[]
  aggregation_mode?: 'average' | 'total' | 'both'
  per_appearance_values?: Record<string, number | null>
  per_appearance_display_values?: Record<string, string>
  totals?: Record<string, number | null>
  total_display_values?: Record<string, string>
  availability?: boolean
  appearances?: number
  requested_team_games?: number
  candidate_count?: number
  entries?: Record<string, unknown>[]
  groups?: Array<{
    key: string
    label: string
    sample_size: number
    raw_values: Record<string, number | null>
    display_values: Record<string, string>
    source_game_ids: number[]
  }>
  series?: Array<{
    game_id: number
    date: string
    value: number
    rolling_mean: number
  }>
  facts?: Array<{
    fingerprint: string
    statement: string
    sample_size: number
    score: number
    source_game_ids: number[]
  }>
  [key: string]: unknown
}

export interface AnalyticsPayload {
  status: 'complete' | 'clarification_required' | 'limited'
  resolved_question: string
  plan: {
    players: Array<Record<string, unknown>>
    timeframe: AnalyticsTimeframe
    filters: Record<string, string | number | boolean>
    stats: string[]
    operations: string[]
    output_type: string
    aggregation_mode: 'average' | 'total' | 'both'
    retrieval_required: boolean
  } | null
  clarification: {
    prompt: string
    choices: Array<{ id: string; label: string; value: string }>
  } | null
  results: AnalyticsResult[]
  coverage: {
    expected_game_count: number
    covered_game_count: number
    missing_game_ids: number[]
    completeness: number
    data_through: string | null
  } | null
}

export interface AnalysisResponse {
  answer: string
  route?: string | null
  classifier?: Record<string, unknown>
  evidence?: Record<string, unknown>[]
  warnings: string[]
  citations: AnalysisCitation[]
  tool_calls?: { tool: string; latency_ms: number; [key: string]: unknown }[]
  refused: boolean
  degraded: boolean
  data_version: string
  request_id: string
  analytics?: AnalyticsPayload | null
  conversation_state?: {
    player_ids: number[]
    game_ids: number[]
    opponent_id: string | null
    date_start: string | null
    date_end: string | null
    periods: number[]
    season_type: 'regular' | 'play_in' | 'playoffs' | null
    home_away: 'home' | 'away' | null
    game_result: 'W' | 'L' | null
    metric: string | null
    route: string | null
    data_version: string | null
  } | null
}

export interface ArchiveStatus {
  season: string
  data_version: string
  games: number
  regular_season_games: number
  postseason_games: number
  reports: number
  activated_at: string | null
  capabilities: string[]
}
