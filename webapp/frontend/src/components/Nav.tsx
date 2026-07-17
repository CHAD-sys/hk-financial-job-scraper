import { Briefcase, Bookmark, Menu, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

interface Props {
  savedCount?: number
}

export default function Nav({ savedCount = 0 }: Props) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { pathname } = useLocation()

  return (
    <header
      style={{ backgroundColor: 'var(--color-nav)', zIndex: 200 }}
      className="sticky top-0 w-full border-b border-white/10"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">

          {/* Wordmark */}
          <button type="button"
            onClick={() => navigate('/')}
            className="flex items-center gap-2.5 cursor-pointer"
            aria-label="FinEx Careers home"
          >
            <span
              className="flex h-8 w-8 items-center justify-center rounded"
              style={{ backgroundColor: 'var(--color-gold)' }}
            >
              <Briefcase size={16} color="#fff" strokeWidth={2} />
            </span>
            <span
              className="text-lg font-semibold tracking-tight select-none"
              style={{ fontFamily: 'var(--font-display)', color: 'var(--color-ink-inverse)' }}
            >
              FinEx{' '}
              <em className="not-italic" style={{ color: 'var(--color-gold)', fontStyle: 'italic' }}>
                Careers
              </em>
            </span>
          </button>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-6" aria-label="Primary navigation">
            {[
              { label: 'Home', path: '/' },
              { label: 'Browse Roles', path: '/jobs' },
              { label: 'About', path: '/about' },
            ].map(({ label, path }) => (
              <button type="button"
                key={label}
                onClick={() => navigate(path)}
                className="text-sm font-medium transition-colors duration-150 cursor-pointer"
                style={{
                  color: pathname === path ? 'var(--color-ink-inverse)' : 'rgba(248,250,252,0.6)',
                }}
                onMouseEnter={e => ((e.currentTarget as HTMLButtonElement).style.color = 'var(--color-ink-inverse)')}
                onMouseLeave={e => {
                  if (pathname !== path)
                    (e.currentTarget as HTMLButtonElement).style.color = 'rgba(248,250,252,0.6)'
                }}
              >
                {label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            {/* Saved jobs */}
            <button type="button"
              onClick={() => navigate('/saved')}
              className="flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-all duration-150 cursor-pointer"
              style={{
                backgroundColor: pathname === '/saved' ? 'var(--color-gold)' : 'rgba(255,255,255,0.08)',
                color: 'var(--color-ink-inverse)',
                border: '1px solid rgba(255,255,255,0.12)',
              }}
              onMouseEnter={e => {
                if (pathname !== '/saved')
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.14)'
              }}
              onMouseLeave={e => {
                if (pathname !== '/saved')
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255,255,255,0.08)'
              }}
              aria-label={`Saved jobs (${savedCount})`}
            >
              <Bookmark
                size={14}
                strokeWidth={1.8}
                fill={savedCount > 0 ? 'currentColor' : 'none'}
              />
              <span>Saved</span>
              {savedCount > 0 && (
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-xs font-bold"
                  style={{ backgroundColor: 'var(--color-gold)', color: '#fff' }}
                >
                  {savedCount}
                </span>
              )}
            </button>

            {/* Mobile toggle */}
            <button type="button"
              className="md:hidden p-2 rounded cursor-pointer"
              style={{ color: 'var(--color-ink-inverse)' }}
              onClick={() => setOpen(o => !o)}
              aria-label="Toggle menu"
              aria-expanded={open}
            >
              {open ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {open && (
        <nav
          className="md:hidden border-t border-white/10 px-6 py-4 flex flex-col gap-4"
          style={{ backgroundColor: 'var(--color-nav)' }}
          aria-label="Mobile navigation"
        >
          {[
            { label: 'Home', path: '/' },
            { label: 'Browse Roles', path: '/jobs' },
            { label: 'Saved Roles', path: '/saved' },
            { label: 'About', path: '/about' },
          ].map(({ label, path }) => (
            <button type="button"
              key={label}
              onClick={() => { navigate(path); setOpen(false) }}
              className="text-sm font-medium text-left cursor-pointer"
              style={{ color: 'rgba(248,250,252,0.8)' }}
            >
              {label}
            </button>
          ))}
        </nav>
      )}
    </header>
  )
}
