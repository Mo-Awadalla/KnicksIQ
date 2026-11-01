import { Link, useLocation } from '@tanstack/react-router'
import { CircleAlert, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import './surfaces.css'

const navItems = [
  { href: '/', label: 'Archive' },
  { href: '/games', label: 'Games' },
  { href: '/reports', label: 'Reports' },
  { href: '/analyst', label: 'Analyst' },
]

export function SurfaceState({
  kind,
  message,
  onRetry,
}: {
  kind: 'loading' | 'error' | 'empty'
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      className={`surface-state surface-state-${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
    >
      {kind === 'loading' ? (
        <Loader2 className='animate-spin' aria-hidden='true' />
      ) : null}
      {kind === 'error' ? <CircleAlert aria-hidden='true' /> : null}
      <span>{message}</span>
      {onRetry ? (
        <Button type='button' variant='outline' size='sm' onClick={onRetry}>
          <RefreshCw aria-hidden='true' /> Try again
        </Button>
      ) : null}
    </div>
  )
}

export function AppShell({
  eyebrow,
  title,
  description,
  children,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  children: React.ReactNode
  actions?: React.ReactNode
}) {
  const location = useLocation()

  return (
    <div className='surface-app'>
      <header className='surface-topbar'>
        <div className='surface-container surface-topbar-inner'>
          <Link
            className='surface-brand'
            to='/'
            aria-label='KnicksIQ archive home'
          >
            <span className='surface-brand-mark' aria-hidden='true'>
              <img
                src='/images/knicksiq-mark-v2.png'
                alt=''
                width='256'
                height='256'
              />
            </span>
            <span>
              <strong>KnicksIQ</strong>
              <small>Season intelligence desk</small>
            </span>
          </Link>
          <nav className='surface-nav' aria-label='Primary navigation'>
            {navItems.map((item) => {
              const active =
                item.href === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  className={active ? 'is-active' : ''}
                  to={item.href}
                  aria-current={active ? 'page' : undefined}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
          <span className='surface-season'>
            2025–26 <span aria-hidden='true'>/</span> archive
          </span>
        </div>
      </header>
      <main className='surface-container surface-main'>
        <header className='surface-page-heading'>
          <div>
            <p className='surface-kicker'>{eyebrow}</p>
            <h1>{title}</h1>
            <p className='surface-description'>{description}</p>
          </div>
          {actions ? (
            <div className='surface-heading-actions'>{actions}</div>
          ) : null}
        </header>
        {children}
      </main>
      <footer className='surface-footer'>
        <div className='surface-container surface-footer-inner'>
          <span>Unofficial fan archive · data-led, source-conscious.</span>
          <nav aria-label='Footer navigation'>
            <Link to='/'>Archive</Link>
            <a href='/sources.html'>Sources</a>
            <a href='/feedback.html'>Feedback</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}

export function MetricStrip({
  items,
}: {
  items: Array<{
    label: string
    value: string
    tone?: 'blue' | 'orange' | 'neutral'
  }>
}) {
  return (
    <div className='metric-strip'>
      {items.map((item) => (
        <div
          className={`metric-cell metric-cell-${item.tone ?? 'neutral'}`}
          key={item.label}
        >
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}
