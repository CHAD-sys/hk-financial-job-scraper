import { useState } from 'react'
import { Play } from 'lucide-react'
import { thumbnailUrl, watchUrl, type FeaturedVideo } from '../content/featuredVideos'

/**
 * A YouTube video card that loads no YouTube code until the visitor asks for it.
 *
 * A real <iframe> embed pulls ~1MB of player JS and sets YouTube cookies on page
 * load — for six embeds, before anyone has pressed play. Instead we show the
 * still frame from i.ytimg.com (an image, no scripts, no cookies) and swap in
 * the iframe only on click, with autoplay so the click still plays the video.
 *
 * Falls back to opening YouTube in a new tab if the iframe is blocked.
 */
export default function VideoFacade({ video }: { video: FeaturedVideo }) {
  const [active, setActive] = useState(false)

  if (active) {
    return (
      <div
        className="relative w-full overflow-hidden rounded-lg"
        style={{ aspectRatio: '16 / 9', backgroundColor: '#000' }}
      >
        <iframe
          className="absolute inset-0 h-full w-full"
          src={`https://www.youtube-nocookie.com/embed/${video.id}?autoplay=1&rel=0`}
          title={video.title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          style={{ border: 0 }}
        />
      </div>
    )
  }

  return (
    <figure className="m-0">
      <button
        type="button"
        onClick={() => setActive(true)}
        className="video-facade group relative block w-full overflow-hidden rounded-lg cursor-pointer"
        style={{
          aspectRatio: '16 / 9',
          border: '1px solid var(--color-border)',
          backgroundColor: 'var(--color-surface-2)',
          padding: 0,
        }}
        aria-label={`Play video: ${video.title}`}
      >
        <img
          src={thumbnailUrl(video.id)}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
        />

        {/* Scrim keeps the play button legible over bright thumbnails */}
        <span
          aria-hidden="true"
          className="absolute inset-0"
          style={{ background: 'linear-gradient(180deg, rgba(11,22,40,0.05) 0%, rgba(11,22,40,0.45) 100%)' }}
        />

        <span
          aria-hidden="true"
          className="video-play absolute left-1/2 top-1/2 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full"
          style={{ backgroundColor: 'var(--color-gold)', boxShadow: 'var(--shadow-raised)' }}
        >
          <Play size={22} strokeWidth={2} fill="#fff" color="#fff" style={{ marginLeft: 2 }} />
        </span>
      </button>

      <figcaption className="mt-3">
        <span
          className="text-xs font-semibold uppercase"
          style={{ color: 'var(--color-gold)', letterSpacing: '0.12em' }}
        >
          {video.topic}
        </span>
        <p className="mt-1 text-sm font-semibold leading-snug" style={{ color: 'var(--color-ink)' }}>
          {video.title}
        </p>
        {/* Escape hatch: if the embed is blocked, this still works. */}
        <a
          href={watchUrl(video.id)}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-block text-xs font-medium"
          style={{ color: 'var(--color-ink-faint)' }}
        >
          Watch on YouTube ↗
        </a>
      </figcaption>
    </figure>
  )
}
