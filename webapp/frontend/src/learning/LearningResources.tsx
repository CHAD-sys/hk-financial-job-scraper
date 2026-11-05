import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, MapPin, Radio } from "lucide-react";
import VideoFacade from "../components/VideoFacade";
import {
  fetchLearningContent,
  type LearningContentResponse,
} from "../api/client";
import {
  FEATURED_VIDEOS,
  CHANNEL_URL,
  type FeaturedVideo,
} from "../content/featuredVideos";
import { EVENTS, EVENTS_URL, type ClubEvent } from "../content/learning";

type LearningEventView = ClubEvent & { id?: string; detail_url?: string };

function hongKongToday(): string {
  const parts = new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Hong_Kong",
  }).formatToParts(new Date());
  const value = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${value.year}-${value.month}-${value.day}`;
}

function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${Number(day)} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(month) - 1]} ${year}`;
}

function formatRefreshDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Hong_Kong",
  }).format(new Date(iso));
}

export default function LearningResources() {
  const [live, setLive] = useState<LearningContentResponse | null>(null);
  useEffect(() => {
    let active = true;
    fetchLearningContent()
      .then((content) => {
        if (active && content.available) setLive(content);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  // The shelf is the hand-picked selection, not the channel's latest uploads.
  const videos: FeaturedVideo[] = FEATURED_VIDEOS;
  const events: LearningEventView[] = live?.events.length
    ? live.events
    : EVENTS;
  const today = hongKongToday();
  const { upcoming, recent } = useMemo(
    () => ({
      upcoming: events
        .filter((event) => event.date >= today)
        .sort((a, b) => a.date.localeCompare(b.date)),
      recent: events
        .filter((event) => event.date < today)
        .sort((a, b) => b.date.localeCompare(a.date)),
    }),
    [events, today],
  );
  const hasUpcoming = upcoming.length > 0;
  return (
    <section
      className="learning-resources mx-auto max-w-7xl px-6 pb-20 lg:px-8"
      id="learning-resources"
    >
      <div className="border-t border-slate-200 pt-16">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <h2 className="font-display text-3xl text-slate-900">
              From the Club
            </h2>
            <p className="mt-2 text-slate-600">
              Interviews, training sessions and market analysis.
            </p>
          </div>
          <a
            href={CHANNEL_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm font-semibold text-slate-800"
          >
            Visit the channel <ArrowUpRight size={16} />
          </a>
        </div>
        <div className="mt-8 grid gap-7 sm:grid-cols-2 lg:grid-cols-3">
          {videos.map((video, index) => (
            <div key={video.id} className={index >= 3 ? "hidden sm:block" : ""}>
              <VideoFacade video={video} />
            </div>
          ))}
        </div>
      </div>
      <section
        className="mt-20 border-t border-slate-200 pt-16"
        aria-labelledby="events-heading"
      >
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <h2
              id="events-heading"
              className="font-display text-3xl text-slate-900"
            >
              {hasUpcoming
                ? "Coming up at FinEx Club"
                : "Where the Club has convened"}
            </h2>
            <p className="mt-2 text-slate-600">
              {hasUpcoming
                ? "Upcoming events and recent sessions."
                : "Recent sessions hosted across Hong Kong."}
            </p>
          </div>
          <a
            href={EVENTS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm font-semibold text-slate-800"
          >
            All events <ArrowUpRight size={16} />
          </a>
        </div>
        {live?.sources.events?.last_success_at && (
          <p className="mt-4 text-xs text-slate-500">
            Updated automatically{" "}
            {formatRefreshDate(live.sources.events.last_success_at)}
          </p>
        )}
        <ul className="mt-8 divide-y divide-slate-200">
          {[...upcoming, ...recent.slice(0, 7)].map((event) => (
            <li
              key={event.id ?? `${event.date}:${event.title}`}
              className="flex flex-col gap-2 py-5 sm:flex-row sm:gap-8"
            >
              <time
                dateTime={event.date}
                className="shrink-0 text-sm font-semibold text-slate-800 sm:w-32"
              >
                {formatDate(event.date)}
              </time>
              <div>
                {event.detail_url ? (
                  <a
                    href={event.detail_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold text-slate-900 hover:underline"
                  >
                    {event.title}
                  </a>
                ) : (
                  <p className="font-semibold text-slate-900">{event.title}</p>
                )}
                <p className="mt-1 inline-flex items-center gap-2 text-sm text-slate-600">
                  {event.online ? <Radio size={14} /> : <MapPin size={14} />}
                  {event.venue}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
