import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ seeker: null as null | { id: string; is_admin: boolean }, loading: false }));
vi.mock("../auth/useAuth", () => ({ useAuth: () => auth }));
vi.mock("./LearningCenterPage", () => ({ default: () => <p>New learning centre</p> }));
vi.mock("./LegacyLearningPage", () => ({ default: () => <p>Current learning page</p> }));
vi.mock("../learning/courses/CoursePage", () => ({ default: () => <p>Course overview</p> }));
vi.mock("../components/Nav", () => ({ default: () => <nav /> }));

const { default: LearningPage } = await import("./LearningPage");
const { default: CourseDetailPage } = await import("./CourseDetailPage");

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/learning" element={<LearningPage />} />
          <Route path="/learning/courses/:courseId" element={<CourseDetailPage />} />
        </Routes>
      </Suspense>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  auth.seeker = null;
  auth.loading = false;
});

describe("admin-only learning centre preview", () => {
  it("keeps the current learning page for guests and ordinary accounts", async () => {
    renderAt("/learning");
    expect(await screen.findByText("Current learning page")).toBeInTheDocument();
    auth.seeker = { id: "s1", is_admin: false };
    renderAt("/learning");
    expect(await screen.findAllByText("Current learning page")).toHaveLength(2);
    expect(screen.queryByText("New learning centre")).not.toBeInTheDocument();
  });

  it("shows the new learning centre to admins", async () => {
    auth.seeker = { id: "a1", is_admin: true };
    renderAt("/learning");
    expect(await screen.findByText("New learning centre")).toBeInTheDocument();
  });

  it("sends non-admins away from course pages", async () => {
    auth.seeker = { id: "s1", is_admin: false };
    renderAt("/learning/courses/quant");
    expect(await screen.findByText("Current learning page")).toBeInTheDocument();
    expect(screen.queryByText("Course overview")).not.toBeInTheDocument();
  });

  it("lets admins open course pages", async () => {
    auth.seeker = { id: "a1", is_admin: true };
    renderAt("/learning/courses/quant");
    expect(await screen.findByText("Course overview")).toBeInTheDocument();
  });
});
