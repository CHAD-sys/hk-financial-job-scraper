import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QUANT_MODULES } from "./quant";
import { brinson, expectedMaxSharpe, riskContributions, riskParity, covariance, PARITY_ASSETS } from "./quantMath";

const auth = vi.hoisted(() => ({ seeker: null as null | { id: string; email: string } }));
vi.mock("../../auth/useAuth", () => ({
  useAuth: () => ({ seeker: auth.seeker, loading: false }),
}));
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  fetchMyLearning: () => Promise.resolve({ member: false, enrolments: [] }),
  fetchMyCapstone: () => Promise.resolve(null),
}));

const { default: CoursePage } = await import("./CoursePage");
const { default: CoursePlayer } = await import("./CoursePlayer");

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/learning" element={<p>Catalogue</p>} />
        <Route path="/learning/courses/:courseId" element={<CoursePage />} />
        <Route path="/learning/courses/:courseId/learn/:week/:item" element={<CoursePlayer />} />
      </Routes>
    </MemoryRouter>,
  );
}
const enrol = () => {
  auth.seeker = { id: "s1", email: "learner@example.com" };
  localStorage.setItem("finex-learning-workspace-v3:s1", JSON.stringify({ progress: { quant: 0 }, reservations: [] }));
};

beforeEach(() => {
  auth.seeker = null;
  localStorage.clear();
});

describe("CoursePage", () => {
  it("renders the full quant programme with brochure and summary downloads", () => {
    renderAt("/learning/courses/quant");
    expect(
      screen.getByRole("heading", { level: 1, name: "Advanced Quantitative Portfolio Management" }),
    ).toBeInTheDocument();
    for (const module of QUANT_MODULES)
      expect(screen.getByText(module.title, { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Brochure$/ })).toHaveAttribute(
      "href",
      "/learning-assets/brochures/quant.pdf",
    );
    expect(screen.getByRole("link", { name: /Course summary/ })).toHaveAttribute(
      "href",
      "/learning-assets/brochures/quant-summary.pdf",
    );
    expect(screen.getAllByRole("link", { name: /Create account to enrol/ })[0]).toHaveAttribute(
      "href",
      "/register",
    );
  });

  it("lists lessons in an outline that links into the course player", () => {
    renderAt("/learning/courses/quant");
    expect(screen.getByText("Free preview")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Mean–variance: the idea that started it all/ })).toHaveAttribute(
      "href",
      "/learning/courses/quant/learn/1/1",
    );
    expect(screen.getAllByText("Enrol to unlock")).toHaveLength(5);
    expect(screen.queryByText(/Markowitz argued/)).not.toBeInTheDocument();
  });

  it("shows one lesson per page with next and previous steps", () => {
    renderAt("/learning/courses/quant/learn/1/2");
    expect(screen.getByRole("heading", { level: 1, name: "CAPM, factors and the cross-section of returns" })).toBeInTheDocument();
    expect(screen.getByText(/Week 1 · Lesson 2 of 3/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Previous/ })).toHaveAttribute("href", "/learning/courses/quant/learn/1/1");
    expect(screen.getByRole("link", { name: /^Next/ })).toHaveAttribute("href", "/learning/courses/quant/learn/1/3");
  });

  it("explains the answer to a knowledge check", () => {
    renderAt("/learning/courses/quant/learn/1/check");
    fireEvent.click(screen.getByRole("button", { name: "1.00" }));
    expect(screen.getByText(/Correct\./)).toBeInTheDocument();
  });

  it("locks later weeks for guests but offers the week 1 notebook", () => {
    renderAt("/learning/courses/quant/learn/1/lab");
    expect(screen.getByRole("link", { name: /Download notebook/ })).toHaveAttribute(
      "href",
      "/learning-assets/notebooks/quant/lab1-value-momentum.ipynb",
    );
    expect(screen.getByText("How to open it in Google Colab")).toBeInTheDocument();
  });

  it("shows a locked screen for a week the guest has not unlocked", () => {
    renderAt("/learning/courses/quant/learn/3/1");
    expect(screen.getByRole("heading", { name: "This week is for enrolled learners" })).toBeInTheDocument();
    expect(screen.queryByText(/Michaud \(1989\)/)).not.toBeInTheDocument();
  });

  it("lets an enrolled learner open any week straight away", () => {
    enrol();
    renderAt("/learning/courses/quant/learn/3/1");
    expect(screen.getByRole("heading", { level: 1, name: "The estimation-error problem" })).toBeInTheDocument();
    expect(screen.queryByText(/Finish week/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Mark complete and continue/ })).toBeInTheDocument();
  });

  it("gates week completion on lessons, the knowledge check and the lab code", async () => {
    enrol();
    const { unmount } = renderAt("/learning/courses/quant/learn/1/1");
    fireEvent.click(screen.getByRole("button", { name: /Mark complete and continue/ }));
    expect(await screen.findByRole("heading", { level: 1, name: /CAPM/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Mark complete and continue/ }));
    expect(await screen.findByRole("heading", { level: 1, name: /fundamental law/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Mark complete and continue/ }));
    fireEvent.click(await screen.findByRole("button", { name: "1.00" }));
    unmount();

    renderAt("/learning/courses/quant/learn/1/lab");
    const complete = screen.getByRole("button", { name: /Complete week 1/ });
    expect(complete).toBeDisabled();
    const input = screen.getByLabelText("Completion code");
    fireEvent.change(input, { target: { value: "FINEX-LAB1-WRONG" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/does not match/);
    expect(complete).toBeDisabled();
    fireEvent.change(input, { target: { value: "finex-lab1-bf739b" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText(/what the data says/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Complete week 1/ })).toBeEnabled();
  });

  it("sends courses without a full page back to the catalogue", () => {
    renderAt("/learning/courses/esg");
    expect(screen.getByText("Catalogue")).toBeInTheDocument();
  });
});

describe("course maths", () => {
  it("Brinson effects sum to the active return", () => {
    const b = brinson();
    expect(b.allocation + b.selection + b.interaction).toBeCloseTo(b.active, 10);
    expect(b.active).toBeCloseTo(0.01795, 6);
  });

  it("risk parity equalises risk contributions", () => {
    const cov = covariance(PARITY_ASSETS.vols, PARITY_ASSETS.corr);
    const rc = riskContributions(riskParity(cov), cov);
    for (const value of rc) expect(value).toBeCloseTo(rc[0], 6);
  });

  it("matches the expected maximum Sharpe quoted in the lesson", () => {
    expect(expectedMaxSharpe(10, 5)).toBeCloseTo(0.7, 1);
    expect(expectedMaxSharpe(1000, 5)).toBeCloseTo(1.46, 1);
  });
});
