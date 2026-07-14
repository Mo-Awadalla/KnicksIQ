import { createFileRoute } from '@tanstack/react-router'
import { SeasonArchivePage } from '@/features/knicks/archive'

export const Route = createFileRoute('/_authenticated/reports/$reportId')({
  component: SeasonArchivePage,
})
