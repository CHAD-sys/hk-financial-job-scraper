import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MTAnnouncementBand from './MTAnnouncementBand'

describe('MTAnnouncementBand', () => {
  it('uses two identical full-width groups for a continuous marquee', () => {
    const { container } = render(<MTAnnouncementBand />)

    expect(screen.getByRole('link', { name: /explore management trainee programmes/i }))
      .toHaveAttribute('href', '#mt-programmes')
    expect(screen.getByRole('link', { name: /post a job for free/i }))
      .toHaveAttribute('href', '/post-a-role')
    expect(container.querySelectorAll('.mt-announcement__group')).toHaveLength(2)
    expect(container.querySelectorAll('.mt-announcement__run')).toHaveLength(4)
  })
})
