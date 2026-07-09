import { createFileRoute } from '@tanstack/react-router'
import { GameDetailPage } from '@/features/knicks'

export const Route = createFileRoute('/_authenticated/games/$gameId')({
  component: RouteComponent,
})

function RouteComponent() {
  const { gameId } = Route.useParams()
  return <GameDetailPage gameId={Number(gameId)} />
}
