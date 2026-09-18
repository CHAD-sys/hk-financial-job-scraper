import { useState } from 'react'
import { ArrowDown } from 'lucide-react'
import { mtCompanyLogo } from '../content/mtCompanyLogos'

export interface MTOpenEmployer {
  company: string
  targetId: string
  roleCount: number
}

function EmployerLogo({ company }: { company: string }) {
  const [failed, setFailed] = useState(false)
  const logo = mtCompanyLogo(company)

  if (!logo.src || failed) {
    return <span className="mt-open-employers__wordmark" aria-hidden="true">{logo.wordmark}</span>
  }

  return <img src={logo.src} alt="" width={240} height={120} onError={() => setFailed(true)} />
}

export default function MTOpenEmployerBanner({
  employers,
  logoCompanies,
  onSelect,
}: {
  employers: readonly MTOpenEmployer[]
  logoCompanies?: readonly string[]
  onSelect?: (targetId: string) => void
}) {
  if (!employers.length) return null

  const companies = [...new Set((logoCompanies?.length ? logoCompanies : employers.map(employer => employer.company)).map(company => company.trim()).filter(Boolean))]

  return (
    <section className="mt-open-employers" aria-labelledby="mt-open-employers-heading">
      <div className="mx-auto max-w-7xl px-6 py-7 lg:px-8">
        <div className="mt-logo-band" aria-label="Management Trainee employers">
          <div className="mt-logo-band__viewport">
            <div className="mt-logo-band__track">
              {[...companies, ...companies].map((company, index) => (
                <span className="mt-logo-band__item" key={`${company}-${index}`} aria-hidden={index >= companies.length}>
                  <EmployerLogo company={company} />
                  <span>{company}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-open-employers__heading">
          <div>
            <p>Open now</p>
            <h2 id="mt-open-employers-heading">Choose an employer to view its active MT role.</h2>
          </div>
        </div>
        <nav className="mt-open-employers__rail" aria-label="Open Management Trainee employers">
          {employers.map(employer => (
            <a
              key={employer.targetId}
              href={`#${employer.targetId}`}
              aria-label={`View the most urgent active role at ${employer.company}`}
              onClick={() => onSelect?.(employer.targetId)}
            >
              <EmployerLogo company={employer.company} />
              <span className="mt-open-employers__name">{employer.company}</span>
              {employer.roleCount > 1 && <small>{employer.roleCount} open roles</small>}
              <ArrowDown size={13} aria-hidden="true" />
            </a>
          ))}
        </nav>
      </div>
    </section>
  )
}
