import type { BoxScore, PlayerGameStat, TeamGameStat } from '@/types'

const countColumns = [
  { key: 'points', label: 'PTS' },
  { key: 'rebounds', label: 'REB' },
  { key: 'assists', label: 'AST' },
  { key: 'steals', label: 'STL' },
  { key: 'blocks', label: 'BLK' },
  { key: 'turnovers', label: 'TO' },
] as const

export function BoxScorePanel({ boxScore }: { boxScore: BoxScore }) {
  const groups: {
    caption: string
    rows: (TeamGameStat | PlayerGameStat)[]
  }[] = [
    { caption: 'Team box score', rows: boxScore.teams },
    { caption: 'Player box score', rows: boxScore.players },
  ]
  return (
    <section
      className='surface-panel detail-panel'
      aria-labelledby='box-score-title'
    >
      <div className='surface-panel-header'>
        <div>
          <p className='surface-kicker'>Game statistics</p>
          <h2 id='box-score-title'>Box score</h2>
        </div>
      </div>
      {groups.every((group) => group.rows.length === 0) ? (
        <p className='panel-empty'>
          No box score statistics are available for this game.
        </p>
      ) : (
        groups.map((group) =>
          group.rows.length > 0 ? (
            <div
              className='table-scroll'
              role='region'
              aria-label={`${group.caption} statistics`}
              tabIndex={0}
              key={group.caption}
            >
              <table className='data-table box-score-table'>
                <caption>{group.caption}</caption>
                <thead>
                  <tr>
                    <th scope='col'>Name</th>
                    <th scope='col'>Team</th>
                    <th scope='col'>MIN</th>
                    {countColumns.map((column) => (
                      <th scope='col' key={column.key}>
                        {column.label}
                      </th>
                    ))}
                    <th scope='col'>FG</th>
                    <th scope='col'>3P</th>
                    <th scope='col'>FT</th>
                    <th scope='col'>+/-</th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) => (
                    <tr key={'player_id' in row ? row.player_id : row.team_id}>
                      <th scope='row'>
                        {'player_name' in row ? row.player_name : row.team_id}
                      </th>
                      <td>{row.team_id}</td>
                      <td className='font-stats'>
                        {'minutes' in row ? row.minutes : '-'}
                      </td>
                      {countColumns.map((column) => (
                        <td className='font-stats' key={column.key}>
                          {row[column.key]}
                        </td>
                      ))}
                      <td className='font-stats'>
                        {row.field_goals_made}/{row.field_goals_attempted}
                      </td>
                      <td className='font-stats'>
                        {row.three_pointers_made}/{row.three_pointers_attempted}
                      </td>
                      <td className='font-stats'>
                        {row.free_throws_made}/{row.free_throws_attempted}
                      </td>
                      <td className='font-stats'>
                        {row.plus_minus > 0 ? '+' : ''}
                        {row.plus_minus}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null
        )
      )}
    </section>
  )
}
