import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { fetchArchiveStatus, fetchReport, fetchReports } from '@/api'
import type { Report } from '@/types'
import { ArrowLeft, ArrowUpRight, FileText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Pagination } from './archive-pagination'
import {
  ARCHIVE_PAGE_SIZE,
  archivePagination,
  useArchivePosition,
} from './archive-position'
import { formatDate } from './game-formatting'
import { SourceValues } from './source-values'
import { AppShell, SurfaceState } from './surface-layout'

interface ReportSummary {
  id: number
  game_id: number
  title: string
  summary: string
  created_at: string
}

function ReportRow({ report }: { report: ReportSummary }) {
  return (
    <Link
      className='report-row'
      to='/reports/$reportId'
      params={{ reportId: String(report.id) }}
      search={(previous) => previous}
    >
      <span className='report-index'>
        R{String(report.id).padStart(2, '0')}
      </span>
      <span>
        <strong>{report.title}</strong>
        <small>
          {formatDate(report.created_at)} · Game {report.game_id}
        </small>
      </span>
      <p>{report.summary}</p>
      <ArrowUpRight aria-hidden='true' />
    </Link>
  )
}

export function ReportsPage() {
  const { page, set } = useArchivePosition()
  const status = useQuery({
    queryKey: ['archive-status'],
    queryFn: () => fetchArchiveStatus(),
  })
  const reports = useQuery({
    queryKey: ['reports', page],
    queryFn: () => fetchReports(archivePagination(page)),
  })
  return (
    <AppShell
      eyebrow='Reviewed output'
      title='Reports with a point of view.'
      description='Game reports turn archive evidence into a readable account of the turning point, the response, and the next adjustment.'
      actions={
        <Badge variant='outline'>
          <FileText aria-hidden='true' /> Reports
        </Badge>
      }
    >
      <section
        className='surface-panel report-index-panel'
        aria-labelledby='report-index-title'
      >
        <div className='surface-panel-header'>
          <div>
            <p className='surface-kicker'>The notebook</p>
            <h2 id='report-index-title'>Game reports</h2>
          </div>
          <span className='panel-count'>
            {status.data?.reports ?? '—'} reports
          </span>
        </div>
        <Pagination
          page={page}
          total={status.data?.reports ?? page * ARCHIVE_PAGE_SIZE}
          onPage={(value) => set({ page: value })}
        />
        {reports.isPending ? (
          <SurfaceState kind='loading' message='Loading reviewed reports…' />
        ) : null}
        {reports.isError ? (
          <SurfaceState
            kind='error'
            message='Reports could not be loaded.'
            onRetry={() => void reports.refetch()}
          />
        ) : null}
        {reports.isSuccess && reports.data.length === 0 ? (
          <SurfaceState
            kind='empty'
            message='No reviewed reports are in the archive yet.'
          />
        ) : null}
        {reports.isSuccess && reports.data.length > 0 ? (
          <div className='report-list'>
            {reports.data.map((report) => (
              <ReportRow key={report.id} report={report} />
            ))}
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}

function ReportSection({
  title,
  children,
  tone,
}: {
  title: string
  children: React.ReactNode
  tone?: 'orange' | 'blue'
}) {
  return (
    <section className={`report-section report-section-${tone ?? 'neutral'}`}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

function ReportSource({
  source,
  report,
}: {
  source: Report['sources'][number]
  report: Report
}) {
  if (typeof source === 'string')
    return (
      <li className='report-source'>
        <SourceValues text={source} />
      </li>
    )
  if (!source || typeof source !== 'object') return null
  const sourceType = typeof source.type === 'string' ? source.type : 'Source'
  const claims = Array.isArray(source.claims) ? source.claims : []
  const claim = claims.find(
    (value): value is string => typeof value === 'string'
  )
  const playerNote = claim?.match(/^player_notes\[(\d+)\]$/)
  const label = playerNote
    ? `${report.player_notes[Number(playerNote[1])]?.split(':')[0] ?? 'Player'} box score`
    : claim === 'turning_point'
      ? 'Selected scoring interval'
      : claim === 'best_stretch'
        ? 'Favorable scoring interval'
        : claim === 'worst_stretch'
          ? 'Opponent scoring interval'
          : sourceType === 'game'
            ? 'Final score'
            : sourceType.replace(/_/g, ' ')
  const url = [source.source_url, source.url].find(
    (value): value is string =>
      typeof value === 'string' && /^https?:\/\//.test(value)
  )
  const start =
    typeof source.start_sequence === 'number' &&
    Number.isSafeInteger(source.start_sequence) &&
    source.start_sequence >= 0
      ? source.start_sequence
      : undefined
  const gameId =
    typeof source.game_id === 'number' &&
    Number.isSafeInteger(source.game_id) &&
    source.game_id > 0
      ? source.game_id
      : report.game_id

  return (
    <li className='report-source'>
      <strong>{label}</strong>
      {typeof source.start_clock === 'string' &&
      typeof source.end_clock === 'string' ? (
        <p>
          Q{String(source.start_period)} {source.start_clock}–Q
          {String(source.end_period)} {source.end_clock}
        </p>
      ) : null}
      {start !== undefined && typeof source.end_sequence === 'number' ? (
        <p>
          Events {start}–{source.end_sequence}, inclusive
        </p>
      ) : null}
      <div className='report-source-links'>
        {sourceType === 'play_by_play' && start !== undefined ? (
          <Link
            to='/games/$gameId'
            params={{ gameId: String(gameId) }}
            hash={`event-${start}`}
          >
            View {label.toLowerCase()} in game
          </Link>
        ) : null}
        {url ? (
          <a href={url} target='_blank' rel='noreferrer'>
            {label} source<span className='sr-only'> (opens in a new tab)</span>
          </a>
        ) : null}
      </div>
    </li>
  )
}

export function ReportDetailPage({ reportId }: { reportId: string }) {
  const id = Number(reportId)
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: () => fetchReport(id),
    enabled: Number.isSafeInteger(id) && id > 0,
  })
  if (report.isPending && Number.isSafeInteger(id) && id > 0)
    return (
      <AppShell
        eyebrow='Report detail'
        title='Loading report.'
        description='Opening the reviewed game notebook.'
      >
        <SurfaceState kind='loading' message='Loading report…' />
      </AppShell>
    )
  if (report.isError || !report.data)
    return (
      <AppShell
        eyebrow='Report detail'
        title='Report unavailable.'
        description='This report could not be found in the archive.'
      >
        <SurfaceState
          kind='error'
          message='The report could not be loaded.'
          onRetry={() => void report.refetch()}
        />
      </AppShell>
    )
  const item: Report = report.data
  return (
    <AppShell
      eyebrow='Reviewed report'
      title={item.title}
      description={item.summary}
      actions={
        <Link
          className='surface-back-link'
          to='/reports'
          search={(previous) => previous}
        >
          <ArrowLeft aria-hidden='true' /> Back to reports
        </Link>
      }
    >
      <div className='report-meta'>
        <Link to='/games/$gameId' params={{ gameId: String(item.game_id) }}>
          Open game {item.game_id}
        </Link>
        <span>
          Published{' '}
          <time dateTime={item.created_at}>{formatDate(item.created_at)}</time>
        </span>
      </div>
      <article className='surface-panel report-detail-panel'>
        <p className='report-interval-note'>
          Scoring intervals cover up to three minutes within one quarter.
        </p>
        <ReportSection title='Selected scoring interval' tone='orange'>
          <p>{item.turning_point}</p>
        </ReportSection>
        <div className='report-two-up'>
          <ReportSection title='Favorable scoring interval' tone='blue'>
            <p>{item.best_stretch}</p>
          </ReportSection>
          <ReportSection title='Opponent scoring interval'>
            <p>{item.worst_stretch}</p>
          </ReportSection>
        </div>
        <div className='report-two-up'>
          <ReportSection title='Player notes'>
            <ul>
              {item.player_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </ReportSection>
          <ReportSection title='Suggested adjustments'>
            {item.suggested_adjustments.length ? (
              <ul>
                {item.suggested_adjustments.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : (
              <p>No adjustments are included in this report.</p>
            )}
          </ReportSection>
        </div>
        {item.sources.length > 0 ? (
          <div className='report-sources'>
            <p className='surface-kicker'>Sources used</p>
            <ul className='report-source-list'>
              {item.sources.map((source, index) => (
                <ReportSource key={index} source={source} report={item} />
              ))}
            </ul>
          </div>
        ) : null}
      </article>
    </AppShell>
  )
}
