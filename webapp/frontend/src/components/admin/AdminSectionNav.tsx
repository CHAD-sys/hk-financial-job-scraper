import { useEffect, useState, type ComponentType } from 'react'
import {
  Activity,
  BarChart3,
  CalendarSync,
  ClipboardCheck,
  SquarePen,
  type LucideProps,
} from 'lucide-react'

interface SectionItem {
  href: string
  label: string
  detail: string
  icon: ComponentType<LucideProps>
  superAdminOnly?: boolean
}

const SECTIONS: SectionItem[] = [
  { href: '#operations-center', label: 'Operations center', detail: 'Reliability · cost · alerts', icon: Activity },
  { href: '#market-intelligence', label: 'Market intelligence', detail: 'Roles · salaries · demand', icon: BarChart3 },
  { href: '#daily-collection', label: 'Daily collection', detail: 'Today’s pipeline totals', icon: CalendarSync },
  { href: '#verification', label: 'Verification', detail: 'Submitted Role review', icon: ClipboardCheck },
  { href: '#job-editor', label: 'Job editor', detail: 'Ultimate Admin controls', icon: SquarePen, superAdminOnly: true },
]

function currentSection() {
  return window.location.hash || '#operations-center'
}

export default function AdminSectionNav({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [activeSection, setActiveSection] = useState(currentSection)

  useEffect(() => {
    const update = () => setActiveSection(currentSection())
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])

  const sections = SECTIONS.filter(section => !section.superAdminOnly || isSuperAdmin)

  return (
    <nav className="admin-section-nav mb-10" aria-label="Admin page sections">
      <div className="admin-section-nav__scroller" tabIndex={0} role="region" aria-label="Admin dashboard sections">
        <div className="admin-section-nav__items" style={{ gridTemplateColumns: `repeat(${sections.length}, minmax(0, 1fr))` }}>
          {sections.map(({ href, label, detail, icon: Icon }) => {
            const active = activeSection === href
            return (
              <a
                key={href}
                href={href}
                className="admin-section-nav__item"
                aria-current={active ? 'location' : undefined}
                onClick={() => setActiveSection(href)}
              >
                <span className="admin-section-nav__icon" aria-hidden="true"><Icon size={17} strokeWidth={2} /></span>
                <span className="min-w-0">
                  <strong>{label}</strong>
                  <small>{detail}</small>
                </span>
              </a>
            )
          })}
        </div>
      </div>
    </nav>
  )
}
