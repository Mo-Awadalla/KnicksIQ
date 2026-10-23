export function ArchiveFooter() {
  return (
    <footer className='archive-footer'>
      <div className='archive-shell landing-footer-masthead'>
        <span>
          KNICKSIQ<span className='landing-period'>.</span>
        </span>
        <p>
          For the fans who
          <br />
          remember the details.
        </p>
      </div>
      <div className='archive-shell archive-footer-inner'>
        <div>
          <strong>About this archive</strong>
          <p>
            KnicksIQ is an unofficial fan project and is not affiliated with,
            endorsed by, or sponsored by the New York Knicks or the NBA. Arena
            photograph by{' '}
            <a
              href='https://unsplash.com/photos/eEnokNtvnoo'
              rel='noreferrer'
              target='_blank'
            >
              With Paul on Unsplash
            </a>
            .
          </p>
        </div>
        <nav aria-label='Policies' className='archive-footer-nav'>
          <a href='/privacy.html'>Privacy</a>
          <a href='/terms.html'>Terms</a>
          <a href='/sources.html'>Sources</a>
          <a href='/feedback.html'>Feedback</a>
        </nav>
      </div>
    </footer>
  )
}
