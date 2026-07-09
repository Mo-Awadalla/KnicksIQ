import { createFileRoute } from '@tanstack/react-router'
import { ReportDetailPage } from '@/features/knicks'

export const Route = createFileRoute('/_authenticated/reports/$reportId')({
  component: RouteComponent,
})

function RouteComponent() {
  const { reportId } = Route.useParams()
  return <ReportDetailPage reportId={Number(reportId)} />
}
