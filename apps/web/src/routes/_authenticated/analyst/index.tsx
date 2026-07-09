import { createFileRoute } from '@tanstack/react-router'
import { AnalystPage } from '@/features/knicks'

export const Route = createFileRoute('/_authenticated/analyst/')({
  component: AnalystPage,
})
