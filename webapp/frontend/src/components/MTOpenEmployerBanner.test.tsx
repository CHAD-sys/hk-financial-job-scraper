import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import MTOpenEmployerBanner from './MTOpenEmployerBanner'

function renderBanner() {
  return render(
    <MemoryRouter>
      <MTOpenEmployerBanner
        employers={[
          { company: 'Goldman Sachs', targetId: 'mt-employer-goldman-sachs', roleCount: 1 },
          { company: 'Standard Chartered', targetId: 'mt-employer-standard-chartered', roleCount: 1 },
        ]}
      />
    </MemoryRouter>,
  )
}

describe('MTOpenEmployerBanner', () => {
  it('keeps the animated employer band available to swipe and keyboard users', () => {
    renderBanner()

    const band = screen.getByRole('group', { name: 'Swipe through Management Trainee employer logos' })
    expect(band).toHaveAttribute('tabindex', '0')
    expect(band).toHaveClass('mt-logo-band__viewport')
    expect(() => fireEvent.keyDown(band, { key: 'ArrowRight' })).not.toThrow()
  })

  it('links each visible logo to that employer page while hiding the loop clone from focus', () => {
    renderBanner()

    const goldmanLinks = screen.getAllByRole('link', { name: 'View Goldman Sachs Management Trainee programmes' })
    const standardCharteredLinks = screen.getAllByRole('link', { name: 'View Standard Chartered Management Trainee programmes' })

    expect(goldmanLinks).toHaveLength(1)
    expect(goldmanLinks[0]).toHaveAttribute('href', '/management-trainee/goldman-sachs')
    expect(standardCharteredLinks).toHaveLength(1)
    expect(standardCharteredLinks[0]).toHaveAttribute('href', '/management-trainee/standard-chartered')
    expect(document.querySelectorAll('.mt-logo-band__item[aria-hidden="true"]')).toHaveLength(2)
  })
})
