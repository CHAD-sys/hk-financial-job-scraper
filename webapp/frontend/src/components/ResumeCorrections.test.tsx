import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ResumeAnalysisOverride, ResumeDocument } from '../api/client'

/** Extraction read this Seeker as "senior" off an internship-only CV. */
const MISREAD: ResumeDocument = {
  filename: 'cv.pdf',
  media_type: 'application/pdf',
  size_bytes: 120_000,
  uploaded_at: '2026-08-18T10:00:00+00:00',
  analysis: {
    skills: ['python', 'sql'],
    role_families: ['data'],
    sectors: [],
    years_experience: null,
    seniority: 'senior',
    certifications: [],
  },
  analysis_extracted: {
    skills: ['python', 'sql'],
    role_families: ['data'],
    sectors: [],
    years_experience: null,
    seniority: 'senior',
    certifications: [],
  },
  analysis_override: {},
}

const corrected: ResumeDocument = {
  ...MISREAD,
  analysis: { ...MISREAD.analysis, seniority: 'intern' },
  analysis_override: { seniority: 'intern' },
}

const correctResumeAnalysis =
  vi.fn<(override: ResumeAnalysisOverride) => Promise<ResumeDocument>>()

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  correctResumeAnalysis: (override: ResumeAnalysisOverride) =>
    correctResumeAnalysis(override),
}))

const { default: ResumeCorrections } = await import('./ResumeCorrections')

beforeEach(() => {
  correctResumeAnalysis.mockReset().mockResolvedValue(corrected)
})

it('stays out of the way until a Seeker says something is wrong', () => {
  render(<ResumeCorrections resume={MISREAD} onSaved={() => {}} />)

  expect(screen.getByRole('button', { name: /correct it/i })).toBeInTheDocument()
  expect(screen.queryByLabelText('Career level')).not.toBeInTheDocument()
})

it('shows what was extracted beside the field being corrected', () => {
  render(<ResumeCorrections resume={MISREAD} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /correct it/i }))

  expect(screen.getByText('We read: senior')).toBeInTheDocument()
  expect(screen.getByText('We read: nothing')).toBeInTheDocument()
})

it('sends only the fields the Seeker actually changed', async () => {
  const onSaved = vi.fn()
  render(<ResumeCorrections resume={MISREAD} onSaved={onSaved} />)
  fireEvent.click(screen.getByRole('button', { name: /correct it/i }))
  fireEvent.change(screen.getByLabelText('Career level'), { target: { value: 'intern' } })
  fireEvent.click(screen.getByRole('button', { name: /save corrections/i }))

  await waitFor(() => expect(correctResumeAnalysis).toHaveBeenCalledWith({
    seniority: 'intern',
    years_experience: null,
    skills: null,
    certifications: null,
  }))
  expect(onSaved).toHaveBeenCalledWith(corrected)
})

it('refuses an impossible number of years before calling the API', async () => {
  render(<ResumeCorrections resume={MISREAD} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /correct it/i }))
  fireEvent.change(screen.getByLabelText('Years of experience'), { target: { value: '99' } })
  fireEvent.click(screen.getByRole('button', { name: /save corrections/i }))

  expect(await screen.findByRole('alert')).toHaveTextContent(/between 0 and 60/i)
  expect(correctResumeAnalysis).not.toHaveBeenCalled()
})

it('lets a Seeker add a skill the reader missed', async () => {
  render(<ResumeCorrections resume={MISREAD} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /correct it/i }))
  fireEvent.change(screen.getByLabelText('Skills'), { target: { value: 'Treasury Operations' } })
  fireEvent.click(screen.getByRole('button', { name: /add skill/i }))
  fireEvent.click(screen.getByRole('button', { name: /save corrections/i }))

  await waitFor(() => expect(correctResumeAnalysis).toHaveBeenCalledWith(
    expect.objectContaining({ skills: ['python', 'sql', 'treasury operations'] }),
  ))
})

it('reports how many fields a Seeker has corrected', () => {
  render(<ResumeCorrections resume={corrected} onSaved={() => {}} />)

  expect(screen.getByText(/1 field corrected by you/i)).toBeInTheDocument()
})

it('can hand a field back to the extractor', async () => {
  render(<ResumeCorrections resume={corrected} onSaved={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: /edit your corrections/i }))
  fireEvent.click(screen.getByRole('button', { name: /use ours/i }))
  fireEvent.click(screen.getByRole('button', { name: /save corrections/i }))

  await waitFor(() => expect(correctResumeAnalysis).toHaveBeenCalledWith(
    expect.objectContaining({ seniority: null }),
  ))
})
