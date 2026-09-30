import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import MultiSelect from './MultiSelect'

const options = Array.from({ length: 30 }, (_, index) => ({
  name: `Company ${index + 1}`,
  count: index + 1,
}))

describe('MultiSelect mobile progressive disclosure', () => {
  it('labels search and reveals long inline lists on request', async () => {
    const user = userEvent.setup()
    render(
      <MultiSelect
        inline
        label="Company"
        options={options}
        selected={[]}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByRole('textbox', { name: 'Search company' })).toBeInTheDocument()
    expect(screen.getAllByRole('option')).toHaveLength(24)

    await user.click(screen.getByRole('button', { name: 'Show all 30 companies' }))
    expect(screen.getAllByRole('option')).toHaveLength(30)
    expect(screen.getByRole('button', { name: 'Show fewer' })).toBeInTheDocument()
  })
})
