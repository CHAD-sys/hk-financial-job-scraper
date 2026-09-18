import { ArrowRight, ArrowUpRight, GraduationCap, MapPin } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchManagementTraineeRoles, type Job } from '../api/client'
import { MT_PROGRAMMES } from '../content/managementTraineePrograms'

export default function MTProgrammeShowcase() {
  const [roles, setRoles] = useState<Job[] | null>(null)

  useEffect(() => {
    let mounted = true
    fetchManagementTraineeRoles()
      .then(response => { if (mounted) setRoles(response.jobs.filter(role => !role.closed).slice(0, 3)) })
      .catch(() => { if (mounted) setRoles([]) })
    return () => { mounted = false }
  }, [])

  return (
    <section id="mt-programmes" className="mt-showcase" aria-labelledby="mt-showcase-heading">
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        <div className="mt-showcase__heading">
          <div>
            <p><GraduationCap size={17} aria-hidden="true" /> FinEx MT Select</p>
            <h2 id="mt-showcase-heading">The strongest MT positions,<br />all in one place.</h2>
          </div>
          <div className="mt-showcase__intro">
            <p>Three high-calibre Management Trainee pathways, selected from the live careers database. They remain here only while their source still says they are active.</p>
            <span role="note">MT only · active roles only · refreshed from the daily pipeline</span>
          </div>
        </div>
        <div className="mt-showcase__grid">
          {roles === null ? <p className="mt-showcase__status" role="status">Loading active MT roles…</p> : roles.length ? roles.map(role => (
            <article className="mt-programme-card" key={`${role.source}:${role.source_id}`}>
              <div className="mt-programme-card__deadline mt-programme-card__deadline--open"><span><strong>Active</strong> · Open in the live careers database</span></div>
              <div className="mt-programme-card__body"><p className="mt-programme-card__industry">{role.job_category ?? 'Management Trainee'}</p><h3>{role.company}</h3><p className="mt-programme-card__type">{role.title}</p><p className="mt-programme-card__checked"><MapPin size={14} aria-hidden="true" /> {role.locations[0] ?? 'Hong Kong'}</p></div>
              <div className="mt-programme-card__actions"><a href={role.url} target="_blank" rel="noopener noreferrer">{role.application_label ?? 'View or apply'} <ArrowUpRight size={15} aria-hidden="true" /></a></div>
            </article>
          )) : <p className="mt-showcase__status" role="status">No active Management Trainee roles are available right now. Browse the directory for programme links.</p>}
        </div>
        <div className="mt-showcase__footer">
          <p><strong>{MT_PROGRAMMES.length}</strong> employer programmes with direct MT links</p>
          <Link to="/management-trainee">View all MT programmes <ArrowRight size={17} aria-hidden="true" /></Link>
        </div>
      </div>
    </section>
  )
}
