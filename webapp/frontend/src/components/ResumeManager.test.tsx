import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ResumeDocument } from '../api/client'

const DOCUMENT: ResumeDocument = {
  filename: 'credit-risk.pdf',
  media_type: 'application/pdf',
  size_bytes: 184_000,
  uploaded_at: '2026-08-10T10:00:00+00:00',
  analysis: {
    skills: ['credit risk', 'sql', 'python'],
    role_families: ['credit', 'risk'],
    sectors: ['Banking'],
    years_experience: 6,
    seniority: 'mid',
    certifications: ['cfa'],
  },
  analysis_extracted: {
    skills: ['credit risk', 'sql', 'python'],
    role_families: ['credit', 'risk'],
    sectors: ['Banking'],
    years_experience: 6,
    seniority: 'mid',
    certifications: ['cfa'],
  },
  analysis_override: {},
}

const fetchResume = vi.fn<() => Promise<ResumeDocument | null>>()
const uploadResume = vi.fn<(file: File) => Promise<ResumeDocument>>()
const deleteResume = vi.fn<() => Promise<void>>()

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchResume: () => fetchResume(),
  uploadResume: (file: File) => uploadResume(file),
  deleteResume: () => deleteResume(),
}))

const { default: ResumeManager } = await import('./ResumeManager')

function renderSubject() {
  return render(<MemoryRouter><ResumeManager /></MemoryRouter>)
}

beforeEach(() => {
  fetchResume.mockReset().mockResolvedValue(null)
  uploadResume.mockReset().mockResolvedValue(DOCUMENT)
  deleteResume.mockReset().mockResolvedValue()
})

describe('ResumeManager', () => {
  it('turns the first valid upload into reviewable evidence', async () => {
    renderSubject()
    expect(await screen.findByRole('button', { name: /Upload your resume/ })).toBeInTheDocument()

    const file = new File(['resume content'], 'credit-risk.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Upload resume'), { target: { files: [file] } })

    await waitFor(() => expect(uploadResume).toHaveBeenCalledWith(file))
    expect(await screen.findByText('credit-risk.pdf')).toBeInTheDocument()
    expect(screen.getByText('Analysed')).toBeInTheDocument()
    expect(screen.getByText('credit risk')).toBeInTheDocument()
    expect(screen.getByText('6 years of experience')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View strong matches' })).toHaveAttribute('href', '/jobs')
  })

  it('rejects unsupported files before making a request', async () => {
    renderSubject()
    await screen.findByRole('button', { name: /Upload your resume/ })
    const file = new File(['plain text'], 'resume.txt', { type: 'text/plain' })

    fireEvent.change(screen.getByLabelText('Upload resume'), { target: { files: [file] } })

    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PDF or DOCX resume')
    expect(uploadResume).not.toHaveBeenCalled()
  })

  it('uses an inline confirmation before removing resume data', async () => {
    fetchResume.mockResolvedValue(DOCUMENT)
    renderSubject()
    await screen.findByText('credit-risk.pdf')

    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(screen.getByText(/Remove this resume and its analysis/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove resume' }))

    await waitFor(() => expect(deleteResume).toHaveBeenCalledOnce())
    expect(await screen.findByRole('button', { name: /Upload your resume/ })).toBeInTheDocument()
  })
})
