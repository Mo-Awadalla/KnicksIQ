import { api } from './client'
import type {
  BadStretch,
  AnalysisResponse,
  GameDetail,
  GameEvent,
  GameSummary,
  Report,
  ScoringRun,
} from '../types'

export async function fetchGames(opts?: {
  season?: string
  teamId?: string
  seasonType?: string
  dataStatus?: string
}): Promise<GameSummary[]> {
  const params: Record<string, string> = {}
  if (opts?.season) params.season = opts.season
  if (opts?.teamId) params.team_id = opts.teamId
  if (opts?.seasonType) params.season_type = opts.seasonType
  if (opts?.dataStatus) params.data_status = opts.dataStatus
  const r = await api.get<GameSummary[]>('/games', { params })
  return r.data
}

export async function fetchGame(id: number): Promise<GameDetail> {
  const r = await api.get<GameDetail>(`/games/${id}`)
  return r.data
}

export async function fetchPlayByPlay(id: number): Promise<GameEvent[]> {
  const r = await api.get<GameEvent[]>(`/games/${id}/play-by-play`)
  return r.data
}

export async function fetchRuns(id: number): Promise<ScoringRun[]> {
  const r = await api.get<ScoringRun[]>(`/games/${id}/runs`)
  return r.data
}

export async function fetchBadStretches(id: number): Promise<BadStretch[]> {
  const r = await api.get<BadStretch[]>(`/games/${id}/bad-stretches`)
  return r.data
}

export async function triggerDetectRuns(id: number) {
  const r = await api.post<{ job_id: string }>(`/games/${id}/detect-runs`)
  return r.data
}

export async function generatePostgameReport(
  gameId: number,
  opts: { includeToolTrace?: boolean; includeSources?: boolean } = {}
) {
  const r = await api.post<Report>('/reports/postgame', {
    game_id: gameId,
    include_tool_trace: opts.includeToolTrace ?? true,
    include_sources: opts.includeSources ?? true,
  })
  return r.data
}

export async function fetchReports(): Promise<Report[]> {
  const r = await api.get<Report[]>('/reports')
  // API returns a summary list; we need to fetch full reports separately if needed.
  return r.data as unknown as Report[]
}

export async function fetchReport(id: number): Promise<Report> {
  const r = await api.get<Report>(`/reports/${id}`)
  return r.data
}

export async function deleteReport(id: number) {
  await api.delete(`/reports/${id}`)
}

export async function askAnalyst(question: string, season = '2025-26') {
  const r = await api.post<AnalysisResponse>('/analysis/query', { question, season })
  return r.data
}
