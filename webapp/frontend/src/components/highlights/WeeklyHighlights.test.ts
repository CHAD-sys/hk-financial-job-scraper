import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { WeeklyHighlightRole } from '../../api/client'
import WeeklyHighlights from './WeeklyHighlights'
import {
  COMMITTEE_PLAYLIST_URL,
  COACH_HIGHLIGHTS,
  VIDEO_HIGHLIGHTS,
  YOUTUBE_CHANNEL_URL,
  mergeWeeklyHighlights,
} from './weeklyHighlights.data'

const API_ROLE = {
  position: 0,
  related_search: 'Private Banking',
  role: {
    source: 'linkedin',
    source_id: '4443781178',
    company: 'JPMorganChase',
    title: 'International Private Bank Managing Director',
    title_en: null,
    locations: ['Hong Kong'],
    seniority: 'Managing Director',
  },
} as WeeklyHighlightRole

describe('weekly highlight destinations', () => {
  it('opens each featured Role inside Careers with a related-role search', () => {
    const roles = mergeWeeklyHighlights([API_ROLE]).filter(item => item.kind === 'role')

    expect(roles.length).toBeGreaterThan(0)
    for (const role of roles) {
      const destination = new URL(role.href, 'https://www.finexcareers.com')

      expect(destination.pathname).toBe('/jobs')
      expect(destination.searchParams.get('q')).toBe(role.desk)
      expect(destination.searchParams.get('role_source')).toBeTruthy()
      expect(destination.searchParams.get('role_id')).toBeTruthy()
      expect(destination.searchParams.has('role_lookup')).toBe(false)
    }
  })

  it('keeps coaches out of the editorial rail and exposes the full public roster separately', () => {
    expect(mergeWeeklyHighlights([API_ROLE]).every(item => item.kind === 'role')).toBe(true)
    expect(COACH_HIGHLIGHTS).toHaveLength(32)
    expect(COACH_HIGHLIGHTS.map(coach => coach.name)).toContain('Andrew Chan')
    expect(COACH_HIGHLIGHTS.every(coach => coach.href.startsWith('https://www.finexclub.org/'))).toBe(true)
  })

  it('moves every unique requested video into its own rail', () => {
    expect(VIDEO_HIGHLIGHTS).toHaveLength(20)
    expect(new Set(VIDEO_HIGHLIGHTS.map(video => video.id)).size).toBe(20)
    expect(VIDEO_HIGHLIGHTS.every(video => video.kind === 'video')).toBe(true)
    expect(VIDEO_HIGHLIGHTS.every(video => video.href.startsWith('https://www.youtube.com/watch?v='))).toBe(true)
    expect(VIDEO_HIGHLIGHTS.map(video => new URL(video.href).searchParams.get('v'))).toEqual([
      'alQ0eelrn1E', 'qUuzybEQdlE', '6g0FAqKApMM', 'm5Bntb8ZMWY', 'B72UtQTBX3M',
      'x1q7-q1Ebnc', 'lmePYW_eBjs', 'ZJp5UK1wog0', 'MCicagWuFGI', 'SWVGD9z4iAI',
      'K4aZUhRrYO8', '1Q9Dzs3Ysv4', 'TfmOMTNadeY', 'yLVerwMgUb4', 'BcsaChO2z9A',
      'Mc6Pc0GlpMI', '6hQHzK5Jd6A', 'DrLhZQj2UGQ', 'SEVKQL6Ag8I', 'iZ1EyIODvaA',
    ])
    expect(mergeWeeklyHighlights([API_ROLE]).some(item => item.kind === 'video')).toBe(false)
  })

  it('offers direct access to the FinEx channel and professional committees playlist', () => {
    const container = document.createElement('div')
    container.innerHTML = renderToStaticMarkup(createElement(WeeklyHighlights))

    expect(container.querySelector(`a[href="${YOUTUBE_CHANNEL_URL}"]`)).not.toBeNull()
    expect(container.querySelector(`a[href="${COMMITTEE_PLAYLIST_URL}"]`)).not.toBeNull()
  })

  it('keeps the seamless duplicate cards pointer-clickable but out of keyboard navigation', () => {
    const container = document.createElement('div')
    container.innerHTML = renderToStaticMarkup(createElement(WeeklyHighlights))

    const duplicateGroups = container.querySelectorAll(
      '.hl__group[aria-hidden="true"], .hl__video-group[aria-hidden="true"], .hl__coach-group[aria-hidden="true"]',
    )
    expect(duplicateGroups).toHaveLength(3)

    for (const group of duplicateGroups) {
      expect(group).not.toHaveAttribute('inert')
    }
    const populatedDuplicateGroups = container.querySelectorAll(
      '.hl__video-group[aria-hidden="true"], .hl__coach-group[aria-hidden="true"]',
    )
    for (const group of populatedDuplicateGroups) {
      const links = group.querySelectorAll('a')
      expect(links.length).toBeGreaterThan(0)
      for (const link of links) expect(link).toHaveAttribute('tabindex', '-1')
    }
  })
})
