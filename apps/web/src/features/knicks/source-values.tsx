/** Render serialized source facts as labels and values, never a raw JSON blob. */
export function SourceValues({ text }: { text: string }) {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return <>{text}</>
  }
  if (!parsed || typeof parsed !== 'object') return <>{text}</>
  return <FactValues value={parsed} />
}

function FactValues({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>Not available</span>
  if (typeof value !== 'object') return <span>{String(value)}</span>
  if (Array.isArray(value)) {
    return (
      <ul>
        {value.map((item, index) => (
          <li key={index}>
            <FactValues value={item} />
          </li>
        ))}
      </ul>
    )
  }
  return (
    <dl className='grid gap-2 text-sm'>
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt className='font-medium capitalize'>{key.replace(/_/g, ' ')}</dt>
          <dd className='text-muted-foreground'>
            <FactValues value={item} />
          </dd>
        </div>
      ))}
    </dl>
  )
}
