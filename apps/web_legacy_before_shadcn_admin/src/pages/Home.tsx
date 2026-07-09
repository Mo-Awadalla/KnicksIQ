import { Link } from 'react-router-dom'

export default function Home() {
  return (
    <div className="space-y-8">
      <section className="text-center py-12">
        <h1 className="text-5xl font-bold mb-4">
          <span className="text-white">Knicks</span>
          <span className="text-knicks-orange">IQ</span>
        </h1>
        <p className="text-xl text-knicks-silver max-w-2xl mx-auto">
          A public Knicks 2025-26 season archive with cached game summaries,
          play-by-play where available, saved reports, and cited analyst answers.
        </p>
      </section>

      <section className="grid md:grid-cols-3 gap-6">
        <Link
          to="/games"
          className="block p-6 bg-gray-900 border border-gray-800 rounded-lg hover:border-knicks-orange transition"
        >
          <h3 className="text-lg font-semibold text-knicks-orange mb-2">Game Browser</h3>
          <p className="text-sm text-knicks-silver">
            Browse Knicks regular-season and playoff games with source and
            completeness badges.
          </p>
        </Link>
        <Link
          to="/analyst"
          className="block p-6 bg-gray-900 border border-gray-800 rounded-lg hover:border-knicks-orange transition"
        >
          <h3 className="text-lg font-semibold text-knicks-orange mb-2">Analyst Chat</h3>
          <p className="text-sm text-knicks-silver">
            Ask grounded Knicks season questions and get answers with game and
            document citations.
          </p>
        </Link>
        <Link
          to="/reports"
          className="block p-6 bg-gray-900 border border-gray-800 rounded-lg hover:border-knicks-orange transition"
        >
          <h3 className="text-lg font-semibold text-knicks-orange mb-2">Saved Reports</h3>
          <p className="text-sm text-knicks-silver">
            Revisit previously generated postgame analyses.
          </p>
        </Link>
      </section>

      <section className="bg-gray-900 border border-gray-800 rounded-lg p-6">
        <h2 className="text-2xl font-bold mb-4">How it works</h2>
        <ol className="space-y-3 text-knicks-silver list-decimal list-inside">
          <li>Season data is cached from the configured NBA data source.</li>
          <li>Games are marked summary-only, play-by-play ready, or analysis ready.</li>
          <li>Event-level claims are only made when cached play-by-play exists.</li>
          <li>Public answers cite games, documents, and source metadata.</li>
        </ol>
      </section>
    </div>
  )
}
