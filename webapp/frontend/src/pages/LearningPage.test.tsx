import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LearningContentResponse } from '../api/client'

const fetchLearningContent = vi.fn<() => Promise<LearningContentResponse>>()

vi.mock('../api/client', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  fetchLearningContent: () => fetchLearningContent(),
}))
vi.mock('../components/Nav', () => ({ default: () => <nav>Navigation</nav> }))
vi.mock('../components/VideoFacade', () => ({
  default: ({ video }: { video: { title: string } }) => <div>{video.title}</div>,
}))

const { default: LearningPage } = await import('./LearningPage')

const LIVE: LearningContentResponse = {
  schema_version: 1,
  available: true,
  updated_at: '2026-08-11T10:00:00Z',
  storage_bytes: 7400,
  sources: {
    events: {
      last_success_at: '2026-08-11T10:00:00Z', last_attempt_at: '2026-08-11T10:00:00Z', error: null,
    },
    videos: {
      last_success_at: '2026-08-11T10:00:00Z', last_attempt_at: '2026-08-11T10:00:00Z', error: null,
    },
  },
  events: [{
    id: 'event-1', title: 'Future Finance Forum', date: '2099-09-14',
    start_at: '2099-09-14T18:00:00+08:00', end_at: null, venue: 'Central Plaza',
    online: false, detail_url: 'https://www.finexclub.org/event-details/future-finance-forum',
    image_url: null,
  }],
  videos: [{
    id: 'qUuzybEQdlE', title: 'Newest FinEx interview', topic: 'Banking & markets',
    published_at: '2026-08-09T13:01:14Z',
    watch_url: 'https://www.youtube.com/watch?v=qUuzybEQdlE',
    thumbnail_url: 'https://i.ytimg.com/vi/qUuzybEQdlE/hqdefault.jpg',
  }],
}

function renderPage() {
  return render(<MemoryRouter><LearningPage /></MemoryRouter>)
}

beforeEach(() => fetchLearningContent.mockReset())

describe('Learning live content', () => {
  it('replaces the compiled shelf with refreshed videos and upcoming events', async () => {
    fetchLearningContent.mockResolvedValue(LIVE)
    renderPage()

    expect(await screen.findByText('Newest FinEx interview')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Coming up at FinEx Club' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Future Finance Forum' })).toHaveAttribute(
      'href', 'https://www.finexclub.org/event-details/future-finance-forum',
    )
    expect(screen.getAllByText(/Updated.*11 Aug 2026/).length).toBeGreaterThan(0)
  })

  it('keeps the curated shelf before the first live snapshot exists', async () => {
    fetchLearningContent.mockResolvedValue({
      ...LIVE, available: false, updated_at: null, events: [], videos: [],
    })
    renderPage()

    await waitFor(() => expect(fetchLearningContent).toHaveBeenCalled())
    expect(screen.getByText('Break down the AI Reality and Confront the Threats')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Where the Club has convened' })).toBeInTheDocument()
  })
})
