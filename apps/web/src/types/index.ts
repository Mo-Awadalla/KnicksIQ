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

export interface AnalysisResponse {
  answer: string
  route: string | null
  classifier: Record<string, unknown>
  evidence: Record<string, unknown>[]
  warnings: string[]
  citations: AnalysisCitation[]
  tool_calls: { tool: string; latency_ms: number; [key: string]: unknown }[]
  refused: boolean
}
