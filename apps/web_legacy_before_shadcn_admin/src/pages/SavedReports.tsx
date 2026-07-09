import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Report } from '../types'

interface ReportSummary {
  id: number
  game_id: number
  title: string
  summary: string
  created_at: string
}

export default function SavedReports() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['reports'],
    queryFn: async () => {
      const r = await api.get<ReportSummary[]>('/reports')
      return r.data
    },
  })

  if (isLoading) return <p>Loading…</p>
  if (error) return <p className="text-red-400">Failed to load reports</p>

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Saved Reports</h1>
      {data?.length === 0 ? (
        <p className="text-knicks-silver">
          No reports yet. Open a game and click "Generate Postgame Autopsy".
        </p>
      ) : (
        <div className="space-y-3">
          {data?.map((r) => (
            <Link
              key={r.id}
              to={`/reports/${r.id}`}
              className="block p-4 bg-gray-900 border border-gray-800 rounded-lg hover:border-knicks-orange transition"
            >
              <div className="text-xs text-knicks-silver mb-1">
                {new Date(r.created_at).toLocaleString()} · game {r.game_id}
              </div>
              <div className="font-semibold text-lg">{r.title}</div>
              <div className="text-sm text-knicks-silver mt-1">{r.summary}</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
