import { createFileRoute } from '@tanstack/react-router'
import { GameDetailPage } from '@/features/knicks/surfaces'

function GameDetailRoute() {
  const { gameId } = Route.useParams()
  return <GameDetailPage gameId={gameId} />
}

export const Route = createFileRoute('/_authenticated/games/$gameId')({
  component: GameDetailRoute,
})
