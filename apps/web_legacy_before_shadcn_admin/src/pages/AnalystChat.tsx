import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { askAnalyst } from '../api'

export default function AnalystChat() {
  const [question, setQuestion] = useState('')
  const analyst = useMutation({
    mutationFn: () => askAnalyst(question),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Knicks Analyst</h1>
        <p className="mt-1 text-sm text-knicks-silver">
          Ask about cached Knicks 2025-26 regular-season and playoff games.
        </p>
      </div>

      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (question.trim()) analyst.mutate()
        }}
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={1200}
          rows={4}
          className="w-full rounded border border-gray-700 bg-gray-900 p-3 text-sm outline-none focus:border-knicks-orange"
          placeholder="Which Knicks game had the biggest run?"
        />
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-knicks-silver">{question.length}/1200</span>
          <button
            type="submit"
            disabled={analyst.isPending || !question.trim()}
            className="rounded bg-knicks-orange px-4 py-2 font-semibold text-knicks-dark disabled:opacity-50"
          >
            {analyst.isPending ? 'Asking...' : 'Ask'}
          </button>
        </div>
      </form>

      {analyst.error && (
        <section className="rounded border border-red-800 bg-red-950 p-4 text-sm">
          Analyst request failed.
        </section>
      )}

      {analyst.data && (
        <section className="space-y-4 rounded border border-gray-800 bg-gray-900 p-5">
          <div>
            <h2 className="mb-2 text-lg font-semibold text-knicks-orange">Answer</h2>
            <p className="text-knicks-silver">{analyst.data.answer}</p>
          </div>

          {analyst.data.citations.length > 0 && (
            <div>
              <h2 className="mb-2 text-lg font-semibold text-knicks-orange">Sources</h2>
              <ul className="space-y-2 text-sm text-knicks-silver">
                {analyst.data.citations.map((citation, index) => (
                  <li key={`${citation.type}-${index}`} className="border-t border-gray-800 pt-2">
                    <span className="font-mono text-xs text-white">{citation.type}</span>{' '}
                    {citation.game_id ? (
                      <Link
                        to={`/games/${citation.game_id}`}
                        className="text-knicks-orange hover:underline"
                      >
                        {citation.title}
                      </Link>
                    ) : (
                      citation.title
                    )}
                    {citation.source_name && (
                      <span className="ml-2 text-xs">({citation.source_name})</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
