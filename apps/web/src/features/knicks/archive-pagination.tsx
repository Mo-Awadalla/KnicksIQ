import { Button } from '@/components/ui/button'
import { ARCHIVE_PAGE_SIZE } from './archive-position'

export function Pagination({
  page,
  total,
  onPage,
}: {
  page: number
  total: number
  onPage: (page: number) => void
}) {
  const totalPages = Math.max(0, Math.ceil(total / ARCHIVE_PAGE_SIZE))
  const current = Math.min(page, totalPages)
  const start = Math.max(1, Math.min(current - 2, totalPages - 4))
  const pages = [
    ...new Set([
      1,
      ...Array.from(
        { length: Math.min(5, totalPages) },
        (_, index) => start + index
      ),
      totalPages,
    ]),
  ].filter((value) => value > 0 && value <= totalPages)
  return (
    <nav aria-label='Pagination' className='filter-row'>
      {pages.map((value) => (
        <Button
          key={value}
          variant={page === value ? 'default' : 'outline'}
          aria-current={page === value ? 'page' : undefined}
          onClick={() => onPage(value)}
        >
          {value}
        </Button>
      ))}
    </nav>
  )
}
