import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import Nav from '../components/Nav'
import MTOpenEmployerBanner from '../components/MTOpenEmployerBanner'
import MTWorkbookProgrammeCard from '../components/MTWorkbookProgrammeCard'
import {
  compareMTProgrammePrestige,
  groupMTWorkbookProgrammesByEmployer,
  MT_WORKBOOK_PROGRAMMES,
  type MTWorkbookEmployer,
} from '../content/mtWorkbookProgrammes'

function employerAnchorId(company: string) {
  return `mt-employer-${company.toLocaleLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')}`
}

export default function ManagementTraineePage() {
  const [query, setQuery] = useState('')

  const programmes = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    if (!term) return MT_WORKBOOK_PROGRAMMES
    return MT_WORKBOOK_PROGRAMMES.filter(programme => programme.company.toLocaleLowerCase().includes(term))
  }, [query])

  const employers = useMemo(() => groupMTWorkbookProgrammesByEmployer(programmes), [programmes])
  const byPrestige = (items: readonly MTWorkbookEmployer[]) => [...items].sort((a, b) => (
    compareMTProgrammePrestige(a.programmes[0], b.programmes[0])
  ))
  const openEmployers = byPrestige(employers.filter(employer => (
    employer.programmes.some(programme => programme.status === 'Active')
  )))
  const closedEmployers = byPrestige(employers.filter(employer => (
    !employer.programmes.some(programme => programme.status === 'Active')
    && employer.programmes.some(programme => programme.status === 'Closed')
  )))
  const unconfirmedEmployers = byPrestige(employers.filter(employer => (
    employer.programmes.every(programme => programme.status === 'N/A')
  )))
  const inactiveEmployers = [...closedEmployers, ...unconfirmedEmployers]
  const openEmployerBannerItems = openEmployers.map(employer => ({
    company: employer.company,
    targetId: employerAnchorId(employer.company),
    roleCount: employer.programmes.filter(programme => programme.status === 'Active').length,
  }))

  return (
    <div className="mt-directory-page">
      <title>Hong Kong Management Trainee Programmes | FinEx Careers</title>
      <meta name="description" content="Explore current and closed Hong Kong Management Trainee employer programmes with direct application links." />
      <Nav />
      <main id="main-content">
        <header className="mt-directory-hero">
          <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
            <p className="mt-directory-hero__kicker">The MT opportunity desk</p>
            <h1>Start where tomorrow&rsquo;s<br />leaders start.</h1>
            <div className="mt-directory-hero__summary">
              <p>Direct employer application links, arranged so current opportunities are the first thing you see.</p>
            </div>
          </div>
        </header>

        <MTOpenEmployerBanner
          employers={openEmployerBannerItems.slice(0, 10)}
          logoCompanies={openEmployerBannerItems.map(employer => employer.company)}
        />

        <section className="mx-auto max-w-7xl px-6 py-12 lg:px-8 lg:py-16" aria-labelledby="mt-directory-heading">
          <div className="mt-directory-toolbar">
            <div>
              <p className="mt-workbook-directory__kicker">Management trainee directory</p>
              <h2 id="mt-directory-heading">Find an employer programme.</h2>
            </div>
            <label className="mt-workbook-directory__search">
              <Search size={18} aria-hidden="true" />
              <span className="sr-only">Search employers</span>
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search employers" />
            </label>
          </div>

          {programmes.length ? (
            <>
              {openEmployers.length > 0 && (
                <section className="mt-workbook-directory__section" aria-labelledby="mt-open-heading">
                  <div className="mt-workbook-directory__heading">
                    <div>
                      <p>Currently open</p>
                      <h2 id="mt-open-heading">Apply while the window is open.</h2>
                    </div>
                    <span>Active in the MT list</span>
                  </div>
                  <div className="mt-directory-grid mt-workbook-directory__grid">
                    {openEmployers.map(employer => (
                      <MTWorkbookProgrammeCard
                        key={employer.company}
                        employer={employer}
                        anchorId={employerAnchorId(employer.company)}
                      />
                    ))}
                  </div>
                </section>
              )}

              {inactiveEmployers.length > 0 && (
                <section className="mt-workbook-directory__section" aria-labelledby="mt-closed-heading">
                  <div className="mt-workbook-directory__heading">
                    <div>
                      <p>Closed &amp; unconfirmed</p>
                      <h2 id="mt-closed-heading">Keep these on your radar.</h2>
                    </div>
                    <span>Closed programmes appear before unconfirmed intakes</span>
                  </div>
                  <div className="mt-directory-grid mt-workbook-directory__grid">
                    {inactiveEmployers.map(employer => (
                      <MTWorkbookProgrammeCard key={employer.company} employer={employer} />
                    ))}
                  </div>
                </section>
              )}
            </>
          ) : (
            <div className="mt-directory-empty">
              <h3>No employer matches that search.</h3>
              <button type="button" onClick={() => setQuery('')}>Clear search</button>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
