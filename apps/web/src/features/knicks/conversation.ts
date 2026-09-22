import type { AnalysisContextMessage } from '@/types'

export const MEMORY_NOTE =
  'Uses your last 10 messages, shortened when needed, plus the current topic and verified facts.'

export function recentContext(
  messages: AnalysisContextMessage[]
): AnalysisContextMessage[] {
  return messages.slice(-10).map(({ role, content }) => ({
    role,
    content: content.slice(0, 2000),
  }))
}
