import { createFileRoute } from '@tanstack/react-router'
import { GamesPage } from '@/features/knicks'

export const Route = createFileRoute('/_authenticated/games/')({
  component: GamesPage,
})
