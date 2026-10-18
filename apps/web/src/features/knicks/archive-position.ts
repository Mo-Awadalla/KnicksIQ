import { useLocation, useNavigate } from '@tanstack/react-router'

export const ARCHIVE_PAGE_SIZE = 50

export function archivePagination(page: number) {
  return { limit: ARCHIVE_PAGE_SIZE, offset: (page - 1) * ARCHIVE_PAGE_SIZE }
}

export function useArchivePosition() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.searchStr)
  const rawPage = Number(params.get('page') || 1)
  const page =
    Number.isSafeInteger(rawPage) &&
    rawPage > 0 &&
    Number.isSafeInteger(archivePagination(rawPage).offset)
      ? rawPage
      : 1
  const set = (values: Record<string, string | number>) => {
    const next: Record<string, string | number> = Object.fromEntries(params)
    Object.entries(values).forEach(([key, value]) => {
      next[key] = value
    })
    void navigate({ to: location.pathname, search: () => next })
  }
  return { page, params, set }
}
