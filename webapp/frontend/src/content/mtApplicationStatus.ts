/**
 * Human-publishable application facts from the MT link audit.
 *
 * This is deliberately sparse. A programme omitted here has not earned an
 * "open" or "closed" claim from a current, explicit employer statement. The
 * audit script writes its wider review queue to outputs/MT_LINK_AUDIT.md.
 */
export type MTApplicationStatus = 'open' | 'closed' | 'upcoming' | 'unavailable'

export interface MTApplicationSnapshot {
  status: MTApplicationStatus
  deadline?: string
  checkedAt: string
  sourceUrl: string
  evidence: string
}

export const MT_APPLICATION_STATUS: Readonly<Record<string, MTApplicationSnapshot>> = {
  'hkex-hong-kong-exchanges-and-clearing': {
    status: 'open',
    deadline: '2026-10-25',
    checkedAt: '2026-09-14',
    sourceUrl: 'https://www.hkexgroup.com/About-HKEX/Careers-at-HKEX/Early-Careers?sc_lang=en',
    evidence: 'Applications are now open until 25 October 2026.',
  },
}
