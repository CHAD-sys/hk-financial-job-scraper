import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SearchHero from './SearchHero'

const CATEGORIES = [
  'Risk Management',
  'Accounting & Finance',
  'Treasury',
  'Investment',
  'Operations',
  'Technology & Transformation',
  'Sales and Business Development',
  'Private Banking',
  'Commercial Banking',
  'Investment Banking',
  'Retail Banking',
  'Sales & Marketing',
  'Legal, Compliance & Audit',
]

describe('SearchHero', () => {
  it('offers every major finance category as a search shortcut', () => {
    const onSearch = vi.fn()
    render(<SearchHero boardTotal={3869} employerCount={240} onSearch={onSearch} />)

    expect(screen.getByText('Major categories')).toBeInTheDocument()
    for (const category of CATEGORIES) {
      expect(screen.getByRole('button', { name: category })).toBeInTheDocument()
    }

    fireEvent.click(screen.getByRole('button', { name: 'Commercial Banking' }))
    expect(onSearch).toHaveBeenCalledWith('Commercial Banking')
  })
})
