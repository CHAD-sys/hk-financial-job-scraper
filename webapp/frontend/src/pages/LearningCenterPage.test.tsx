import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LearningContentResponse } from "../api/client";

const fetchLearningContent = vi.fn<() => Promise<LearningContentResponse>>();

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  fetchLearningContent: () => fetchLearningContent(),
}));
vi.mock("../components/Nav", () => ({ default: () => <nav>Navigation</nav> }));
vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ seeker: null, loading: false }),
}));
vi.mock("../components/VideoFacade", () => ({
  default: ({ video }: { video: { title: string } }) => (
    <div>{video.title}</div>
  ),
}));

const { default: LearningPage } = await import("./LearningCenterPage");

const LIVE: LearningContentResponse = {
  schema_version: 1,
  available: true,
  updated_at: "2026-08-11T10:00:00Z",
  storage_bytes: 7400,
  sources: {
    events: {
      last_success_at: "2026-08-11T10:00:00Z",
      last_attempt_at: "2026-08-11T10:00:00Z",
      error: null,
    },
    videos: {
      last_success_at: "2026-08-11T10:00:00Z",
      last_attempt_at: "2026-08-11T10:00:00Z",
      error: null,
    },
  },
  events: [
    {
      id: "event-1",
      title: "Future Finance Forum",
      date: "2099-09-14",
      start_at: "2099-09-14T18:00:00+08:00",
      end_at: null,
      venue: "Central Plaza",
      online: false,
      detail_url:
        "https://www.finexclub.org/event-details/future-finance-forum",
      image_url: null,
    },
  ],
  videos: [
    {
      id: "qUuzybEQdlE",
      title: "Newest FinEx interview",
      topic: "Banking & markets",
      published_at: "2026-08-09T13:01:14Z",
      watch_url: "https://www.youtube.com/watch?v=qUuzybEQdlE",
      thumbnail_url: "https://i.ytimg.com/vi/qUuzybEQdlE/hqdefault.jpg",
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <LearningPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  fetchLearningContent.mockReset();
  localStorage.clear();
  window.location.hash = "";
});

describe("Learning live content", () => {
  it("uses one fixed palette even when an old dark-mode preference is saved", () => {
    localStorage.setItem("finex-learning-theme", "dark");
    fetchLearningContent.mockResolvedValue({
      ...LIVE,
      available: false,
      events: [],
      videos: [],
    });
    renderPage();
    expect(document.querySelector(".learning-site")).not.toHaveAttribute(
      "data-learning-theme",
    );
    expect(
      screen.queryByRole("button", { name: /Switch to .* mode/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps the hand-picked video shelf and refreshes upcoming events", async () => {
    fetchLearningContent.mockResolvedValue(LIVE);
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Coming up at FinEx Club" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Newest FinEx interview")).not.toBeInTheDocument();
    expect(
      screen.getByText("Break down the AI Reality and Confront the Threats"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Future Finance Forum" }),
    ).toHaveAttribute(
      "href",
      "https://www.finexclub.org/event-details/future-finance-forum",
    );
    expect(screen.getAllByText(/Updated.*11 Aug 2026/).length).toBeGreaterThan(
      0,
    );
  });

  it("keeps the curated shelf before the first live snapshot exists", async () => {
    fetchLearningContent.mockResolvedValue({
      ...LIVE,
      available: false,
      updated_at: null,
      events: [],
      videos: [],
    });
    renderPage();

    await waitFor(() => expect(fetchLearningContent).toHaveBeenCalled());
    expect(
      screen.getByText("Break down the AI Reality and Confront the Threats"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Where the Club has convened" }),
    ).toBeInTheDocument();
  });
});
