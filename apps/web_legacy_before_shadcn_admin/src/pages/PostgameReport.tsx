import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { fetchReport } from '../api'

export default function PostgameReport() {
  const { id } = useParams<{ id: string }>()
  const reportId = Number(id)

  const { data: report, isLoading, error } = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => fetchReport(reportId),
  })

  if (isLoading) return <p>Loading report…</p>
  if (error || !report) return <p className="text-red-400">Report not found</p>

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={`/games/${report.game_id}`}
          className="text-knicks-orange hover:underline text-sm"
        >
          ← Back to game
        </Link>
        <h1 className="text-3xl font-bold mt-2">{report.title}</h1>
        <p className="text-knicks-silver text-sm mt-1">
          Generated {new Date(report.created_at).toLocaleString()}
        </p>
      </div>

      <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-lg font-semibold text-knicks-orange mb-2">Summary</h2>
        <p className="text-knicks-silver">{report.summary}</p>
      </section>

      <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-lg font-semibold text-knicks-orange mb-2">Turning Point</h2>
        <p>{report.turning_point}</p>
      </section>

      <div className="grid md:grid-cols-2 gap-4">
        <section className="bg-blue-950 border border-knicks-blue rounded-lg p-5">
          <h2 className="text-lg font-semibold text-knicks-orange mb-2">Best Stretch</h2>
          <p className="text-sm">{report.best_stretch}</p>
        </section>
        <section className="bg-red-950 border border-red-800 rounded-lg p-5">
          <h2 className="text-lg font-semibold text-red-300 mb-2">Worst Stretch</h2>
          <p className="text-sm">{report.worst_stretch}</p>
        </section>
      </div>

      {report.suggested_adjustments.length > 0 && (
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-lg font-semibold text-knicks-orange mb-2">
            Suggested Adjustments
          </h2>
          <ul className="list-disc list-inside space-y-1 text-knicks-silver">
            {report.suggested_adjustments.map((adj, i) => (
              <li key={i}>{adj}</li>
            ))}
          </ul>
        </section>
      )}

      {report.sources.length > 0 && (
        <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-lg font-semibold text-knicks-orange mb-2">Sources</h2>
          <ul className="text-sm text-knicks-silver space-y-1">
            {report.sources.map((s, i) => (
              <li key={i}>
                <span className="font-mono text-xs bg-gray-800 px-1 py-0.5 rounded">
                  {s.type}
                </span>{' '}
                {Object.entries(s)
                  .filter(([k]) => k !== 'type')
                  .map(([k, v]) => `${k}=${v}`)
                  .join(' · ')}
              </li>
            ))}
          </ul>
        </section>
      )}

    </div>
  )
}
