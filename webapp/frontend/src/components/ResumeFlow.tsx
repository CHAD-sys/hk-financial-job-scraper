import { BadgeCheck, FileSearch, Upload } from 'lucide-react'

export default function ResumeFlow({ className = '' }: { className?: string }) {
  return (
    <ol className={`resume-flow ${className}`.trim()} aria-label="How resume matching works">
      <li><Upload size={17} strokeWidth={2} aria-hidden="true" /><span>Upload</span></li>
      <li><FileSearch size={17} strokeWidth={2} aria-hidden="true" /><span>Analyse</span></li>
      <li><BadgeCheck size={17} strokeWidth={2} aria-hidden="true" /><span>Match</span></li>
    </ol>
  )
}
