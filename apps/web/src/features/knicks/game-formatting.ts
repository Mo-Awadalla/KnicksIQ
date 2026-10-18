import type { GameSummary } from '@/types'

export function formatDate(value: string) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(value))
}

export function teamLabel(id: string, fallback?: string | null) {
  if (fallback) return fallback
  if (id === 'NYK') return 'New York Knicks'
  return id
}

export function shortTeamLabel(id: string, fallback?: string | null) {
  if (fallback) return fallback
  if (id === 'NYK') return 'NYK'
  return id
}

export function resultForGame(game: GameSummary) {
  if (game.status !== 'final') return game.status
  return game.winner_team_id === 'NYK' ? 'W' : 'L'
}
