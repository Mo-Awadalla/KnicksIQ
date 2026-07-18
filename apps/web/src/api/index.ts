import type {
  BadStretch,
  AnalysisResponse,
  AnalysisContextMessage,
  ArchiveStatus,
  GameDetail,
  GameEvent,
  GameSummary,
  Player,
  Report,
  ScoringRun,
} from '../types'
import { api } from './client'

export interface ReportSummary {
  id: number
  game_id: number
  title: string
  summary: string
  created_at: string
}

export async function fetchGames(opts?: {
  season?: string
  teamId?: string
  seasonType?: string
  dataStatus?: string
  limit?: number
  offset?: number
}): Promise<GameSummary[]> {
  const params: Record<string, number | string> = {}
  if (opts?.season) params.season = opts.season
  if (opts?.teamId) params.team_id = opts.teamId
  if (opts?.seasonType) params.season_type = opts.seasonType
  if (opts?.dataStatus) params.data_status = opts.dataStatus
  if (opts?.limit) params.limit = opts.limit
  if (opts?.offset) params.offset = opts.offset
  const r = await api.get<GameSummary[]>('/games', { params })
  return r.data
}

export async function fetchArchiveStatus(): Promise<ArchiveStatus> {
  const response = await api.get<ArchiveStatus>('/archive/status')
  return response.data
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

export async function fetchPlayers(opts?: {
  teamId?: string
  search?: string
  limit?: number
  offset?: number
}): Promise<Player[]> {
  const params: Record<string, string | number> = {}
  if (opts?.teamId) params.team_id = opts.teamId
  if (opts?.search) params.search = opts.search
  if (opts?.limit) params.limit = opts.limit
  if (opts?.offset) params.offset = opts.offset
  const r = await api.get<Player[]>('/players', { params })
  return r.data
}

export async function fetchReports(): Promise<ReportSummary[]> {
  const r = await api.get<ReportSummary[]>('/reports')
  return r.data
}

export async function fetchReport(id: number): Promise<Report> {
  const r = await api.get<Report>(`/reports/${id}`)
  return r.data
}

export async function askAnalyst(
  question: string,
  season = '2025-26',
  context: AnalysisContextMessage[] = [],
  conversationState?: AnalysisResponse['conversation_state']
) {
  const r = await api.post<AnalysisResponse>('/analysis/query', {
    question,
    season,
    context,
    conversation_state: conversationState,
  })
  return r.data
}
