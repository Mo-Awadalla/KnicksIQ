import http from 'k6/http'
import { check } from 'k6'
import { Trend } from 'k6/metrics'

const initialReadiness = new Trend('initial_readiness_ms')

export const options = {
  scenarios: {
    archive: {
      executor: 'constant-vus',
      exec: 'archive',
      vus: 10,
      duration: '30s',
    },
    analyst: {
      executor: 'per-vu-iterations',
      exec: 'analyst',
      vus: 10,
      iterations: 1,
      maxDuration: '30s',
    },
  },
  thresholds: {
    'http_req_failed{phase:warm}': ['rate<0.01'],
    'http_req_duration{route:archive,phase:warm}': ['p(95)<1000'],
    'http_req_duration{route:analyst,phase:warm}': ['p(95)<4000'],
  },
}

const base = __ENV.BASE_URL

export function setup() {
  const started = Date.now()
  const ready = http.get(`${base}/archive/status`, {
    timeout: '60s', tags: { route: 'archive', phase: 'initial-readiness' },
  })
  initialReadiness.add(Date.now() - started)
  if (ready.status !== 200) throw new Error('Initial archive readiness failed')
  const warmup = http.post(`${base}/analysis/query`, JSON.stringify({
    question: 'How many games did the Knicks win?', season: '2025-26', context: [],
  }), { headers: { 'Content-Type': 'application/json' },
    tags: { route: 'analyst', phase: 'warmup' }, timeout: '60s' })
  if (warmup.status !== 200) throw new Error('Analyst warmup failed')
}

export function archive() {
  const archive = http.get(`${base}/archive/status`, { tags: { route: 'archive', phase: 'warm' } })
  check(archive, { 'archive available': (response) => response.status === 200 })
}

export function analyst() {
  const analyst = http.post(
    `${base}/analysis/query`,
    JSON.stringify({ question: 'What was the Knicks record this season?' }),
    { headers: { 'Content-Type': 'application/json' }, tags: { route: 'analyst', phase: 'warm' } }
  )
  check(analyst, { 'analyst factual response': (response) => response.status === 200 })
}
