import { useEffect, useState, type ComponentType } from 'react'
import {
  Activity,
  BarChart3,
  CalendarSync,
  Building2,
  ClipboardCheck,
  IdCard,
  SquarePen,
  Users,
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
  { href: '#user-activity', label: 'Seeker accounts', detail: 'Signups · active · returning', icon: Users },
  { href: '#market-intelligence', label: 'Market intelligence', detail: 'Roles · salaries · demand', icon: BarChart3 },
  { href: '#daily-collection', label: 'Daily collection', detail: 'Today’s pipeline totals', icon: CalendarSync },
  { href: '#verification', label: 'Verification', detail: 'Submitted Role review', icon: ClipboardCheck },
  { href: '#accounts', label: 'Account directory', detail: 'Every Seeker and Employer', icon: IdCard, superAdminOnly: true },
  // Ultimate-Admin-only for the same reason as the directory above it: this
  // joins one Employer's identity to their submissions and their Roles.
  { href: '#employer-view', label: 'Employer view', detail: 'One Employer’s own side', icon: Building2, superAdminOnly: true },
  // Not superAdminOnly since ADR 0019 — every admin may correct a Role, so
  // every admin needs the category that reaches the editor. The account
  // directory above stays Ultimate-Admin-only; that one did not change.
  { href: '#job-editor', label: 'Job editor', detail: 'Search and correct any Role', icon: SquarePen },
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
        <div className="admin-section-nav__items">
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
