import http from 'k6/http'
import { check } from 'k6'

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
    http_req_failed: ['rate<0.01'],
    'http_req_duration{route:archive}': ['p(95)<1000'],
    'http_req_duration{route:analyst}': ['p(95)<4000'],
  },
}

const base = __ENV.BASE_URL

export function archive() {
  const archive = http.get(`${base}/archive/status`, { tags: { route: 'archive' } })
  check(archive, { 'archive available': (response) => response.status === 200 })
}

export function analyst() {
  const analyst = http.post(
    `${base}/analysis/query`,
    JSON.stringify({ question: 'What was the Knicks record this season?' }),
    { headers: { 'Content-Type': 'application/json' }, tags: { route: 'analyst' } }
  )
  check(analyst, { 'analyst factual response': (response) => response.status === 200 })
}
