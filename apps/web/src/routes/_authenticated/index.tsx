import { createFileRoute } from '@tanstack/react-router'
import { GamesCommandCenter } from '@/features/knicks'

export const Route = createFileRoute('/_authenticated/')({
  component: GamesCommandCenter,
})
