import { createFileRoute } from '@tanstack/react-router'
import { ReportsPage } from '@/features/knicks'

export const Route = createFileRoute('/_authenticated/reports/')({
  component: ReportsPage,
})
