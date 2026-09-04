import { createFileRoute } from '@tanstack/react-router'
import { ReportDetailPage } from '@/features/knicks/surfaces'

function ReportDetailRoute() {
  const { reportId } = Route.useParams()
  return <ReportDetailPage reportId={reportId} />
}

export const Route = createFileRoute('/_authenticated/reports/$reportId')({
  component: ReportDetailRoute,
})
