import { createFileRoute } from '@tanstack/react-router'
import { ReportsPage } from '@/features/knicks/surfaces'

export const Route = createFileRoute('/_authenticated/reports/')({
  component: ReportsPage,
})
