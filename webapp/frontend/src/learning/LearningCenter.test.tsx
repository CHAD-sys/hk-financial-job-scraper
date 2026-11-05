import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LearningCenter from "./LearningCenter";

const auth = vi.hoisted(() => ({ signedIn: false }));
vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({
    seeker: auth.signedIn
      ? { id: "learner-1", display_name: "Sam Lee", email: "sam@example.com" }
      : null,
    loading: false,
  }),
}));
vi.mock("../api/client", () => ({
  fetchMyLearning: vi.fn().mockResolvedValue({ member: false, enrolments: [] }),
}));

function page() {
  return (
    <MemoryRouter>
      <LearningCenter />
    </MemoryRouter>
  );
}
beforeEach(() => {
  auth.signedIn = false;
  localStorage.clear();
  window.location.hash = "";
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = true;
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value: function (this: HTMLDialogElement) {
      this.open = false;
    },
  });
  HTMLElement.prototype.scrollIntoView = vi.fn();
  window.matchMedia = vi.fn().mockReturnValue({ matches: true });
});

describe("Integrated learning centre", () => {
  it("starts as a fresh guest even when the previous demo has saved activity", () => {
    localStorage.setItem(
      "finex-learning-v2-demo-v1",
      JSON.stringify({
        progress: { quant: 2, esg: 1 },
        reservations: ["macro-workshop"],
      }),
    );
    render(page());
    expect(
      screen.getByRole("progressbar", { name: "Annual CPD goal" }),
    ).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getAllByRole("button", { name: "Enrol now" })).toHaveLength(
      5,
    );
    expect(
      screen.queryByText(
        /Alexander|Welcome back|On track|Active preview member/,
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Continue learning" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Sign in to reserve" }),
    ).toHaveLength(2);
    expect(
      screen.getByRole("link", { name: /Create account/ }),
    ).toHaveAttribute("href", "/register");
  });

  it("keeps course discovery public and directs guest enrolment into real account routes", () => {
    render(page());
    fireEvent.change(screen.getByRole("textbox", { name: "Search courses" }), {
      target: { value: "private" },
    });
    expect(
      screen.getByRole("heading", {
        name: "Private Equity Deal Structuring & LBO Valuation",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: "Advanced Quantitative Portfolio Management",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Enrol now" }));
    const modal = screen.getByRole("dialog", {
      name: "Your next chapter starts here.",
    });
    expect(
      within(modal).getByRole("link", { name: "Create account" }),
    ).toHaveAttribute("href", "/register");
    expect(
      within(modal).getByRole("link", { name: "Sign in" }),
    ).toHaveAttribute("href", "/signin");
    expect(within(modal).queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "Annual CPD goal" }),
    ).toHaveAttribute("aria-valuenow", "0");
  });

  it("starts new signed-in accounts empty and saves only their own subsequent learning", () => {
    auth.signedIn = true;
    const { unmount } = render(page());
    expect(
      screen.getByRole("progressbar", { name: "Annual CPD goal" }),
    ).toHaveAttribute("aria-valuenow", "0");
    // Course 0 (quant) enrols straight into the lesson player; course 1 keeps the workspace dialog.
    fireEvent.click(screen.getAllByRole("button", { name: "Enrol now" })[1]);
    const form = screen.getByRole("dialog", {
      name: "Your next chapter starts here.",
    });
    expect(within(form).getByLabelText("Full name")).toHaveValue("Sam Lee");
    fireEvent.click(
      within(form).getByRole("button", { name: "Confirm demo enrolment" }),
    );
    const workspace = screen.getByRole("dialog", {
      name: "Your learning workspace",
    });
    fireEvent.click(
      within(workspace).getByRole("button", { name: "Complete next module" }),
    );
    fireEvent.click(
      within(workspace).getByRole("button", { name: "Close dialog" }),
    );
    expect(
      screen.getByRole("progressbar", { name: "Annual CPD goal" }),
    ).toHaveAttribute("aria-valuenow", "10");
    unmount();
    auth.signedIn = false;
    render(page());
    expect(
      screen.getByRole("progressbar", { name: "Annual CPD goal" }),
    ).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getAllByRole("button", { name: "Enrol now" })).toHaveLength(
      5,
    );
  });
});
