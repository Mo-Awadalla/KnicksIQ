import { createFileRoute } from '@tanstack/react-router'
import { GamesPage } from '@/features/knicks/surfaces'

export const Route = createFileRoute('/_authenticated/games/')({
  component: GamesPage,
})
