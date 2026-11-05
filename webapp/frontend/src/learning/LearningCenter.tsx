import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Award,
  Bell,
  BookOpen,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  Clock3,
  GraduationCap,
  Headphones,
  LockKeyhole,
  UserRound,
  Play,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  Users,
  X,
} from "lucide-react";
import {
  COURSES,
  TRAINERS,
  WORKSHOPS,
  brochureFor,
  money,
  summaryFor,
  trainerFor,
  type PreviewCourse,
  type Trainer,
} from "./catalogue";
import { useLearningWorkspace } from "./useLearningWorkspace";
import { useAuth } from "../auth/useAuth";
import { fetchMyLearning } from "../api/client";
import { Link, useNavigate } from "react-router-dom";
import { useCourseProgress } from "./courses/useCourseProgress";
import { COURSE_ITEMS } from "./courses/useQuantCourse";
import PreviewDialog from "./PreviewDialog";

/** Programmes with a full course page. */
const FULL_COURSES = new Set(["quant"]);

type View = "catalogue" | "learning" | "faculty" | "support";
type Overlay =
  | { type: "course" | "enrol" | "progress"; course: PreviewCourse }
  | { type: "trainer"; trainer: Trainer }
  | { type: "cpd" | "account" }
  | null;
const VIEWS: { id: View; label: string }[] = [
  { id: "catalogue", label: "Course catalogue" },
  { id: "learning", label: "My learning" },
  { id: "faculty", label: "Faculty profiles" },
  { id: "support", label: "Member support" },
];
const getView = (): View =>
  VIEWS.find((view) => `#${view.id}` === window.location.hash)?.id ??
  "catalogue";

function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div
      className="v2-progress"
      role="progressbar"
      aria-label={label}
      aria-valuenow={Math.round(Math.min(100, Math.max(0, value)))}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span style={{ transform: `scaleX(${Math.min(100, value) / 100})` }} />
    </div>
  );
}
function Avatar({
  trainer,
  small = false,
}: {
  trainer: Trainer;
  small?: boolean;
}) {
  return (
    <span
      className={`v2-avatar v2-avatar--${trainer.tone}${small ? " v2-avatar--small" : ""}`}
      aria-hidden="true"
    >
      {trainer.initials}
    </span>
  );
}

export default function LearningCenter({ children }: { children?: ReactNode }) {
  const { seeker, loading: authLoading } = useAuth();
  const learning = useLearningWorkspace(seeker?.id ?? null);
  const quantProgress = useCourseProgress(seeker?.id ?? null, "quant");
  const routerNavigate = useNavigate();
  /** Straight into the lesson player at the first unfinished step; other courses keep the workspace dialog. */
  function openCourse(course: PreviewCourse) {
    if (!FULL_COURSES.has(course.id)) {
      setOverlay({ type: "progress", course });
      return;
    }
    const week = Math.min((learning.progress[course.id] ?? 0) + 1, 6);
    const items = COURSE_ITEMS.filter((it) => it.week === week);
    const next =
      items.find((it) =>
        it.kind === "lesson"
          ? !quantProgress.lessonDone(`${it.week}.${it.item}`)
          : it.kind === "check"
            ? !quantProgress.checkDone(it.week)
            : !quantProgress.labDone(it.week),
      ) ?? items[0];
    routerNavigate(`/learning/courses/${course.id}/learn/${next.week}/${next.item}`);
  }
  const [membership, setMembership] = useState({ owner: "", member: false });
  const member =
    !!seeker && membership.owner === seeker.id && membership.member;
  const displayName = seeker?.display_name || "Your account";
  const initials = displayName
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
  useEffect(() => {
    if (!seeker) return;
    let active = true;
    fetchMyLearning()
      .then((record) => {
        if (active) setMembership({ owner: seeker.id, member: record.member });
      })
      .catch(() => {
        if (active) setMembership({ owner: seeker.id, member: false });
      });
    return () => {
      active = false;
    };
  }, [seeker]);
  const [view, setView] = useState<View>(getView);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All categories");
  const [level, setLevel] = useState("All levels");
  const [sort, setSort] = useState("Recommended");
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [notice, setNotice] = useState("");
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const contentRef = useRef<HTMLElement>(null);
  const enrolled = COURSES.filter((course) => course.id in learning.progress);
  const filtered = COURSES.filter(
    (course) =>
      `${course.title} ${course.description} ${course.category} ${trainerFor(course).name}`
        .toLowerCase()
        .includes(search.trim().toLowerCase()) &&
      (category === "All categories" || course.category === category) &&
      (level === "All levels" || course.level === level),
  ).sort((a, b) =>
    sort === "Price: low to high"
      ? a.price - b.price
      : sort === "Most CPD hours"
        ? b.hours - a.hours
        : 0,
  );

  useEffect(() => {
    const onHash = () => setView(getView());
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    };
  }, []);
  function navigate(next: View) {
    window.location.hash = next;
    setView(next);
    requestAnimationFrame(() =>
      contentRef.current?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
        block: "start",
      }),
    );
  }
  function toast(message: string) {
    setNotice(message);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(""), 4500);
  }
  function submitEnrolment(
    event: FormEvent<HTMLFormElement>,
    course: PreviewCourse,
  ) {
    event.preventDefault();
    if (!seeker) {
      setOverlay({ type: "account" });
      return;
    }
    learning.enrol(course.id);
    if (FULL_COURSES.has(course.id)) {
      setOverlay(null);
      routerNavigate(`/learning/courses/${course.id}/learn/1/1`);
      return;
    }
    setOverlay({ type: "progress", course });
    toast(`You're enrolled in ${course.title}. Your demo place is saved.`);
  }
  const completed = COURSES.filter(
    (course) => learning.progress[course.id] === course.modules.length,
  ).length;

  return (
    <div className="v2-app">
      <a className="v2-skip" href="#v2-main">
        Skip to learning content
      </a>
      <header className="v2-header">
        <div className="v2-container v2-header__inner">
          <a
            href="#catalogue"
            onClick={(event) => {
              event.preventDefault();
              navigate("catalogue");
            }}
            className="v2-brand"
          >
            <GraduationCap size={24} />
            <strong>Learning</strong>
          </a>
          <nav className="v2-nav" aria-label="Learning portal navigation">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={view === item.id ? "is-active" : ""}
                aria-current={view === item.id ? "page" : undefined}
                aria-label={item.label}
                onClick={() => navigate(item.id)}
              >
                <span className="v2-nav__label">{item.label}</span>
                <span className="v2-nav__compact" aria-hidden="true">
                  {item.id === "catalogue"
                    ? "Courses"
                    : item.id === "learning"
                      ? "My learning"
                      : item.id === "faculty"
                        ? "Faculty"
                        : "Support"}
                </span>
                {item.id === "learning" && enrolled.length > 0 && (
                  <span className="v2-nav__count">{enrolled.length}</span>
                )}
              </button>
            ))}
          </nav>
          <div className="v2-header-actions">
            {seeker ? (
              <button
                type="button"
                className="v2-member"
                onClick={() => setOverlay({ type: "account" })}
              >
                <span className="v2-member__avatar">{initials}</span>
                <span>
                  <strong>{displayName}</strong>
                  <small>
                    {member ? "FinEx Club member" : "FinEx Careers account"}
                  </small>
                </span>
              </button>
            ) : (
              !authLoading && (
                <>
                  <Link
                    className="v2-signin-link"
                    to="/signin"
                    state={{ from: "/learning" }}
                  >
                    Sign in
                  </Link>
                  <Link
                    className="v2-button v2-button--gold v2-register-link"
                    to="/register"
                    state={{ from: "/learning" }}
                  >
                    Create account <ArrowUpRight size={14} />
                  </Link>
                </>
              )
            )}
          </div>
        </div>
      </header>

      <main id="v2-main">
        <section className="v2-hero v2-container" aria-labelledby="v2-title">
          <div className="v2-hero__copy">
            <h1 id="v2-title">
              Build the expertise.
              <br />
              <span>Lead what’s next.</span>
            </h1>
            <p>
              Deepen your knowledge. Sharpen your judgement.
              <br className="v2-desktop-break" /> Executive learning, built
              around your next move.
            </p>
            <div className="v2-hero__features">
              <span>
                <ShieldCheck size={16} /> CPD-focused learning
              </span>
              <span>
                <Users size={16} /> Practitioner-led
              </span>
              <span>
                <LockKeyhole size={15} /> Member benefits
              </span>
            </div>
          </div>
          <aside className="v2-cpd" aria-label="CPD hours tracker">
            <div className="v2-cpd__top">
              <span className="v2-cpd__icon">
                <Award size={23} />
              </span>
              <div>
                <h2>Your CPD, in focus</h2>
                <p>2026 learning cycle</p>
              </div>
              <span className="v2-badge v2-badge--gold">
                {learning.hours > 0 ? "In progress" : "Not started"}
              </span>
            </div>
            <div className="v2-cpd__numbers">
              <span>Earned learning hours</span>
              <strong>
                {learning.hours}
                <span> / 60 hrs</span>
              </strong>
            </div>
            <ProgressBar
              value={(learning.hours / 60) * 100}
              label="Annual CPD goal"
            />
            <p className="v2-cpd__remaining">
              {!seeker ? (
                "Create an account to save your courses and start tracking your learning hours."
              ) : learning.hours >= 60 ? (
                "Annual learning goal complete. Keep the momentum."
              ) : (
                <>
                  <strong>{60 - learning.hours} hours</strong> to your annual
                  goal. Every course is a step forward.
                </>
              )}
            </p>
            <button
              type="button"
              className="v2-cpd__footer"
              onClick={() => setOverlay({ type: seeker ? "cpd" : "account" })}
            >
              <span>
                <BookOpen size={15} />{" "}
                {seeker ? "Your learning record" : "Your journey starts here"}
              </span>
              <span>
                {seeker ? "View details" : "Get started"}{" "}
                <ChevronRight size={15} />
              </span>
            </button>
          </aside>
        </section>
        <div className="v2-container v2-trust-strip">
          <span>
            <strong>5</strong> executive programmes
          </span>
          <span>
            <strong>132</strong> CPD hours to explore
          </span>
          <span>
            <Star size={14} fill="currentColor" />
            <strong>4.9 / 5</strong> faculty rating
          </span>
          <a href="/learning-assets/brochures/programme-guide.pdf" download>
            <ArrowDownToLine size={15} /> Download programme guide
          </a>
        </div>

        <p className="v2-container v2-catalogue-notice">
          Illustrative catalogue. Prices, ratings, trainers and dates are sample
          content for this local preview.
        </p>

        <section
          ref={contentRef}
          id="v2-content"
          className="v2-content v2-container"
          aria-label="Learning content"
        >
          {view === "catalogue" && (
            <>
              {enrolled.length > 0 && (
                <div className="v2-continue">
                  <span className="v2-continue__lead">
                    <span className="v2-continue__icon">
                      <Play size={15} fill="currentColor" />
                    </span>
                    <span>
                      Welcome back, {displayName.split(" ")[0]}.
                      <strong>Keep your momentum.</strong>
                    </span>
                  </span>
                  <div className="v2-continue__courses">
                    {enrolled.slice(0, 2).map((course) => (
                      <button
                        type="button"
                        key={course.id}
                        onClick={() => openCourse(course)}
                      >
                        <span>
                          <strong>
                            {course.id === "quant"
                              ? "Quantitative portfolio management"
                              : course.title}
                          </strong>
                          <small>
                            Module{" "}
                            {Math.min(
                              learning.progress[course.id] + 1,
                              course.modules.length,
                            )}{" "}
                            of {course.modules.length} <span>·</span>{" "}
                            {Math.round(
                              (learning.progress[course.id] /
                                course.modules.length) *
                                100,
                            )}
                            % complete
                          </small>
                        </span>
                        <span className="v2-continue__play">
                          <Play size={12} fill="currentColor" />
                        </span>
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    className="v2-text-link"
                    onClick={() => navigate("learning")}
                  >
                    My learning <ArrowUpRight size={15} />
                  </button>
                </div>
              )}
              <div className="v2-section-heading">
                <div>
                  <h2>Invest in your next chapter.</h2>
                  <p>
                    Focused programmes. Practical expertise. A lasting edge.
                  </p>
                </div>
                <span className="v2-result-count">
                  {filtered.length} programmes
                </span>
              </div>
              <div className="v2-filters">
                <label className="v2-search">
                  <Search size={18} />
                  <span className="v2-sr-only">Search courses</span>
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search by skill, topic or strategy…"
                  />
                  {search && (
                    <button
                      type="button"
                      onClick={() => setSearch("")}
                      aria-label="Clear search"
                    >
                      <X size={15} />
                    </button>
                  )}
                </label>
                <label className="v2-filter-select">
                  <SlidersHorizontal size={15} />
                  <span className="v2-sr-only">Course category</span>
                  <select
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                  >
                    <option>All categories</option>
                    {Array.from(
                      new Set(COURSES.map((course) => course.category)),
                    ).map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
                <label className="v2-filter-select">
                  <span className="v2-sr-only">Course level</span>
                  <select
                    value={level}
                    onChange={(event) => setLevel(event.target.value)}
                  >
                    <option>All levels</option>
                    <option>Advanced</option>
                    <option>Intermediate</option>
                  </select>
                </label>
              </div>
              <div className="v2-catalogue-meta">
                <span>Curated for finance professionals</span>
                <label>
                  Sort by{" "}
                  <select
                    aria-label="Sort courses"
                    value={sort}
                    onChange={(event) => setSort(event.target.value)}
                  >
                    <option>Recommended</option>
                    <option>Price: low to high</option>
                    <option>Most CPD hours</option>
                  </select>
                </label>
              </div>
              {filtered.length ? (
                <div className="v2-course-grid">
                  {filtered.map((course) => (
                    <CourseCard
                      key={course.id}
                      course={course}
                      member={member}
                      progress={learning.progress[course.id]}
                      onSummary={() => setOverlay({ type: "course", course })}
                      onTrainer={() =>
                        setOverlay({
                          type: "trainer",
                          trainer: trainerFor(course),
                        })
                      }
                      onAction={() =>
                        course.id in learning.progress
                          ? openCourse(course)
                          : setOverlay({ type: "enrol", course })
                      }
                      onOpen={() =>
                        FULL_COURSES.has(course.id)
                          ? routerNavigate(`/learning/courses/${course.id}`)
                          : setOverlay({ type: "course", course })
                      }
                    />
                  ))}
                </div>
              ) : (
                <div className="v2-empty">
                  <Search size={28} />
                  <h3>No programmes match your search</h3>
                  <p>
                    Try another keyword, or clear your filters to explore all
                    five courses.
                  </p>
                  <button
                    className="v2-button v2-button--gold"
                    type="button"
                    onClick={() => {
                      setSearch("");
                      setCategory("All categories");
                      setLevel("All levels");
                    }}
                  >
                    Clear filters
                  </button>
                </div>
              )}
            </>
          )}

          {view === "learning" && (
            <>
              <div className="v2-section-heading">
                <div>
                  <h2>Your learning, moving forward.</h2>
                  <p>
                    {enrolled.length} enrolled programmes · {completed}{" "}
                    completed · {learning.hours} CPD hours earned
                  </p>
                </div>
                <button
                  type="button"
                  className="v2-text-link"
                  onClick={() => navigate("catalogue")}
                >
                  Explore courses <ArrowUpRight size={15} />
                </button>
              </div>
              {enrolled.length === 0 && (
                <div className="v2-empty v2-first-learning">
                  <BookOpen size={29} />
                  <h3>
                    {seeker
                      ? "Your first course starts here."
                      : "Make room for what’s next."}
                  </h3>
                  <p>
                    {seeker
                      ? "Browse the catalogue and choose a programme. Your learning progress will appear here."
                      : "Create your free FinEx Careers account to enrol in courses and keep your learning in one place."}
                  </p>
                  {seeker ? (
                    <button
                      type="button"
                      className="v2-button v2-button--gold"
                      onClick={() => navigate("catalogue")}
                    >
                      Explore courses <ArrowRight size={16} />
                    </button>
                  ) : (
                    <div className="v2-guest-actions">
                      <Link
                        className="v2-button v2-button--gold"
                        to="/register"
                        state={{ from: "/learning" }}
                      >
                        Create account <ArrowRight size={16} />
                      </Link>
                      <Link
                        className="v2-button v2-button--outline"
                        to="/signin"
                        state={{ from: "/learning" }}
                      >
                        Sign in
                      </Link>
                    </div>
                  )}
                </div>
              )}
              <div className="v2-learning-list">
                {enrolled.map((course) => {
                  const count = learning.progress[course.id];
                  return (
                    <article
                      className="v2-learning-item is-clickable"
                      key={course.id}
                      onClick={(event) => {
                        if (!(event.target as HTMLElement).closest("a, button")) openCourse(course);
                      }}
                    >
                      <span
                        className={`v2-learning-item__symbol v2-avatar--${trainerFor(course).tone}`}
                      >
                        <BookOpen size={26} />
                      </span>
                      <div className="v2-learning-item__copy">
                        <span className="v2-category">{course.category}</span>
                        <h3>{course.title}</h3>
                        <p>
                          {count} of {course.modules.length} modules completed ·{" "}
                          {Math.round(
                            (count / course.modules.length) * course.hours,
                          )}{" "}
                          / {course.hours} CPD hours
                        </p>
                        <ProgressBar
                          value={(count / course.modules.length) * 100}
                          label={`${course.title} learning progress`}
                        />
                      </div>
                      <button
                        type="button"
                        className="v2-button v2-button--gold"
                        onClick={() => openCourse(course)}
                      >
                        {count === course.modules.length
                          ? "Review programme"
                          : "Continue learning"}{" "}
                        <ArrowRight size={16} />
                      </button>
                    </article>
                  );
                })}
              </div>
              <div className="v2-reservations">
                <h3>Your workshop reservations</h3>
                {learning.reservations.length ? (
                  WORKSHOPS.filter((item) =>
                    learning.reservations.includes(item.id),
                  ).map((item) => (
                    <p key={item.id}>
                      <CheckCheck size={17} /> {item.title}
                      <span>
                        {item.date} · {item.time}
                      </span>
                    </p>
                  ))
                ) : (
                  <p>
                    No workshops reserved yet. Explore the member sessions
                    below.
                  </p>
                )}
              </div>
            </>
          )}
          {view === "faculty" && (
            <>
              <div className="v2-section-heading">
                <div>
                  <h2>Learn from those who lead.</h2>
                  <p>
                    Meet your programme faculty. Illustrative profiles for this
                    design preview.
                  </p>
                </div>
              </div>
              <div className="v2-faculty-grid">
                {TRAINERS.map((trainer) => (
                  <article key={trainer.id} className="v2-faculty-card">
                    <Avatar trainer={trainer} />
                    <h3>{trainer.name}</h3>
                    <p className="v2-faculty-role">{trainer.role}</p>
                    <p>{trainer.bio}</p>
                    <button
                      type="button"
                      className="v2-text-link"
                      onClick={() => setOverlay({ type: "trainer", trainer })}
                    >
                      View profile & courses <ArrowRight size={16} />
                    </button>
                  </article>
                ))}
              </div>
            </>
          )}
          {view === "support" && (
            <>
              <div className="v2-section-heading">
                <div>
                  <h2>A little guidance goes a long way.</h2>
                  <p>
                    Your questions about learning, enrolment and membership,
                    answered.
                  </p>
                </div>
                <Headphones size={30} />
              </div>
              <div className="v2-faq">
                {[
                  [
                    "How do I enrol in a course?",
                    "Choose a programme, review its summary and select Enrol now. In this preview, confirming the form adds the course to My learning without taking a payment.",
                  ],
                  [
                    "How are CPD hours tracked?",
                    "Each completed module updates the programme progress bar and your annual CPD tracker. Every new account starts with zero completed modules and zero earned hours. These are illustrative values, not an accreditation record.",
                  ],
                  [
                    "What is included with membership?",
                    "Verified FinEx Club members can access the displayed member course prices and exclusive workshop reservations. Real membership terms and eligibility will be confirmed by FinEx Club.",
                  ],
                  [
                    "Where can I find the course brochure?",
                    "Every programme card has a brochure download with the summary, trainer profile, course modules and sample price. The programme guide includes the full catalogue.",
                  ],
                  [
                    "Where is my learning progress saved?",
                    "This design preview saves enrolments, module progress and workshop reservations in this browser. Your learning record starts empty and is kept separately for your signed-in account.",
                  ],
                ].map(([question, answer]) => (
                  <details key={question}>
                    <summary>
                      {question}
                      <ChevronDown size={18} />
                    </summary>
                    <p>{answer}</p>
                  </details>
                ))}
              </div>
            </>
          )}

          <div className="v2-bottom-grid">
            <section
              className="v2-workshops"
              aria-labelledby="v2-workshops-title"
            >
              <div className="v2-bottom-heading">
                <div>
                  <h2 id="v2-workshops-title">
                    <CalendarDays size={19} /> Beyond the classroom
                  </h2>
                  <p>Live conversations, reserved for members.</p>
                </div>
                <span className="v2-badge v2-badge--gold">
                  <LockKeyhole size={11} /> Members only
                </span>
              </div>
              <div className="v2-workshop-list">
                {WORKSHOPS.map((workshop) => {
                  const reserved = learning.reservations.includes(workshop.id);
                  return (
                    <article className="v2-workshop" key={workshop.id}>
                      <div className="v2-date-block">
                        <span>{workshop.month}</span>
                        <strong>{workshop.day}</strong>
                      </div>
                      <div className="v2-workshop__copy">
                        <span>
                          {workshop.kind} <i /> {workshop.time}
                        </span>
                        <h3>{workshop.title}</h3>
                        <p>
                          With {workshop.trainer} <span>·</span>{" "}
                          {workshop.credits} CPD hrs
                        </p>
                      </div>
                      <button
                        type="button"
                        className={`v2-workshop__button${reserved ? " is-reserved" : ""}`}
                        disabled={reserved}
                        onClick={() => {
                          if (!seeker || !member) {
                            setOverlay({ type: "account" });
                            return;
                          }
                          learning.reserve(workshop.id);
                          toast(
                            `Seat reserved for ${workshop.date}. See My learning for details.`,
                          );
                        }}
                      >
                        {reserved ? (
                          <>
                            <Check size={14} /> Reserved
                          </>
                        ) : (
                          <>
                            {seeker
                              ? member
                                ? "Reserve a seat"
                                : "Member access"
                              : "Sign in to reserve"}{" "}
                            <ArrowUpRight size={14} />
                          </>
                        )}
                      </button>
                    </article>
                  );
                })}
              </div>
              <span className="v2-member-inclusion">
                <Check size={13} /> Exclusive to verified FinEx Club members
              </span>
            </section>
            <aside
              className="v2-announcements"
              aria-labelledby="v2-announcements-title"
            >
              <div className="v2-bottom-heading">
                <div>
                  <h2 id="v2-announcements-title">
                    <Bell size={18} /> From the learning desk
                  </h2>
                  <p>A few things worth knowing.</p>
                </div>
              </div>
              <article>
                <div>
                  <span>Programme update</span>
                  <time dateTime="2026-11-03">03 Nov</time>
                </div>
                <h3>Your next cohort starts this month.</h3>
                <p>
                  Explore the new executive programme lineup and find the right
                  fit for your learning plan.
                </p>
                <button
                  type="button"
                  className="v2-text-link"
                  onClick={() => {
                    navigate("catalogue");
                    setSearch("");
                    setCategory("All categories");
                    setLevel("All levels");
                  }}
                >
                  Explore programmes <ArrowRight size={14} />
                </button>
              </article>
              <article>
                <div>
                  <span>Member benefit</span>
                  <time dateTime="2026-11-01">01 Nov</time>
                </div>
                <h3>Make your membership go further.</h3>
                <p>
                  FinEx Club members can access 20% savings across the sample
                  programme catalogue. Sign in to check your membership status.
                </p>
              </article>
            </aside>
          </div>
        </section>
        {children}
      </main>
      <footer className="v2-footer">
        <div className="v2-container">
          <a
            href="#catalogue"
            className="v2-footer-brand"
            onClick={(event) => {
              event.preventDefault();
              navigate("catalogue");
            }}
          >
            <GraduationCap size={21} /> FinEx Learning{" "}
            <span>Part of FinEx Careers</span>
          </a>
          <nav aria-label="Footer navigation">
            <button type="button" onClick={() => navigate("catalogue")}>
              Course catalogue
            </button>
            <button type="button" onClick={() => navigate("learning")}>
              My learning
            </button>
            <button type="button" onClick={() => navigate("support")}>
              Help & support
            </button>
          </nav>
        </div>
        <p className="v2-container v2-footer-note">
          A Financial Executive Club platform. This local preview uses
          illustrative course, pricing, faculty and CPD information.
        </p>
      </footer>
      {notice && (
        <div className="v2-toast" role="status">
          <CheckCheck size={18} />
          <span>{notice}</span>
          <button
            type="button"
            onClick={() => setNotice("")}
            aria-label="Dismiss notification"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {!learning.persistent && (
        <div role="status" className="v2-storage-note">
          Browser storage is unavailable. Changes will last for this visit.
        </div>
      )}
      {overlay && (
        <PreviewDialog
          title={
            overlay.type === "course"
              ? "Programme overview"
              : overlay.type === "enrol"
                ? "Your next chapter starts here."
                : overlay.type === "progress"
                  ? "Your learning workspace"
                  : overlay.type === "trainer"
                    ? "Meet your faculty"
                    : overlay.type === "cpd"
                      ? "Your 2026 CPD record"
                      : "Your FinEx account"
          }
          onClose={() => setOverlay(null)}
          wide={overlay.type === "course" || overlay.type === "progress"}
        >
          {overlay.type === "course" && (
            <div className="v2-course-detail">
              <div className="v2-detail-top">
                <span className="v2-category">{overlay.course.category}</span>
                <span>
                  <Star size={13} fill="currentColor" /> {overlay.course.rating}{" "}
                  ({overlay.course.reviews} reviews)
                </span>
              </div>
              <h3>{overlay.course.title}</h3>
              <p>{overlay.course.description}</p>
              <div className="v2-detail-facts">
                <span>
                  <Clock3 size={16} /> {overlay.course.duration}
                </span>
                <span>
                  <Award size={16} /> {overlay.course.hours} CPD hrs
                </span>
                <span>{overlay.course.level}</span>
              </div>
              <h4>What you'll take away</h4>
              <ul className="v2-outcomes">
                {overlay.course.outcomes.map((item) => (
                  <li key={item}>
                    <Check size={16} /> {item}
                  </li>
                ))}
              </ul>
              <h4>Your programme, module by module</h4>
              <ol className="v2-module-preview">
                {overlay.course.modules.map((item, index) => (
                  <li key={item}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    {item}
                  </li>
                ))}
              </ol>
              {FULL_COURSES.has(overlay.course.id) && (
                <div className="v2-detail-full">
                  <Link
                    className="v2-button v2-button--outline"
                    to={`/learning/courses/${overlay.course.id}`}
                  >
                    <BookOpen size={15} /> Open the full course
                  </Link>
                  <a
                    className="v2-text-link"
                    href={summaryFor(overlay.course.id)}
                    download
                  >
                    <ArrowDownToLine size={15} /> Course summary (PDF)
                  </a>
                </div>
              )}
              <div className="v2-detail-trainer">
                <Avatar trainer={trainerFor(overlay.course)} small />
                <div>
                  <strong>{trainerFor(overlay.course).name}</strong>
                  <p>{trainerFor(overlay.course).role}</p>
                </div>
                <button
                  className="v2-text-link"
                  type="button"
                  onClick={() =>
                    setOverlay({
                      type: "trainer",
                      trainer: trainerFor(overlay.course),
                    })
                  }
                >
                  View profile <ArrowUpRight size={14} />
                </button>
              </div>
              <div className="v2-detail-actions">
                <div>
                  <span>{member ? "Member price" : "Course price"}</span>
                  <strong>
                    {money(
                      member ? overlay.course.price : overlay.course.fullPrice,
                    )}
                  </strong>
                </div>
                <a
                  className="v2-button v2-button--outline"
                  href={brochureFor(overlay.course)}
                  download
                >
                  <ArrowDownToLine size={15} /> Brochure
                </a>
                <button
                  type="button"
                  className="v2-button v2-button--gold"
                  onClick={() =>
                    overlay.course.id in learning.progress
                      ? openCourse(overlay.course)
                      : setOverlay({ type: "enrol", course: overlay.course })
                  }
                >
                  {overlay.course.id in learning.progress
                    ? "Continue learning"
                    : "Enrol now"}{" "}
                  <ArrowRight size={16} />
                </button>
              </div>
            </div>
          )}
          {overlay.type === "enrol" && !seeker && (
            <div className="v2-account-detail v2-guest-prompt">
              <span className="v2-guest-icon">
                <GraduationCap size={29} />
              </span>
              <h3>Start with a free account.</h3>
              <p>
                Create a FinEx Careers account to enrol in{" "}
                <strong>{overlay.course.title}</strong> and keep track of your
                learning.
              </p>
              <div className="v2-enrol-price">
                <span>
                  Course price
                  <small>Member price {money(overlay.course.price)}</small>
                </span>
                <strong>{money(overlay.course.fullPrice)}</strong>
              </div>
              <div className="v2-guest-actions">
                <Link
                  className="v2-button v2-button--gold"
                  to="/register"
                  state={{ from: "/learning" }}
                >
                  Create account <ArrowRight size={16} />
                </Link>
                <Link
                  className="v2-button v2-button--outline"
                  to="/signin"
                  state={{ from: "/learning" }}
                >
                  Sign in
                </Link>
              </div>
            </div>
          )}
          {overlay.type === "enrol" && seeker && (
            <form
              className="v2-enrol-form"
              onSubmit={(event) => submitEnrolment(event, overlay.course)}
            >
              <span className="v2-badge v2-badge--gold">
                Demo enrolment · No payment taken
              </span>
              <h3>{overlay.course.title}</h3>
              <p>
                {overlay.course.duration} <span>·</span> {overlay.course.hours}{" "}
                CPD hrs <span>·</span> Online learning
              </p>
              <div className="v2-enrol-price">
                <span>
                  {member ? "Your member price" : "Course price"}{" "}
                  <small>
                    {member
                      ? "20% membership saving applied"
                      : `Member price ${money(overlay.course.price)}`}
                  </small>
                </span>
                <strong>
                  {money(
                    member ? overlay.course.price : overlay.course.fullPrice,
                  )}
                </strong>
              </div>
              <label>
                Full name
                <input
                  name="name"
                  required
                  defaultValue={seeker?.display_name ?? ""}
                  autoComplete="name"
                />
              </label>
              <label>
                Email address
                <input
                  name="email"
                  type="email"
                  required
                  placeholder="you@example.com"
                  defaultValue={seeker?.email ?? ""}
                  autoComplete="email"
                />
              </label>
              <p className="v2-form-note">
                This preview adds the programme to My learning. Your details
                stay in this form and are not sent to a server.
              </p>
              <button className="v2-button v2-button--gold" type="submit">
                Confirm demo enrolment <ArrowRight size={17} />
              </button>
            </form>
          )}
          {overlay.type === "progress" && (
            <div className="v2-workspace">
              <span className="v2-category">{overlay.course.category}</span>
              <h3>{overlay.course.title}</h3>
              <div className="v2-workspace__progress">
                <span>
                  {learning.progress[overlay.course.id] ?? 0} of{" "}
                  {overlay.course.modules.length} modules complete
                </span>
                <strong>
                  {Math.round(
                    ((learning.progress[overlay.course.id] ?? 0) /
                      overlay.course.modules.length) *
                      100,
                  )}
                  %
                </strong>
              </div>
              <ProgressBar
                value={
                  ((learning.progress[overlay.course.id] ?? 0) /
                    overlay.course.modules.length) *
                  100
                }
                label="Course completion"
              />
              <ol className="v2-workspace__modules">
                {overlay.course.modules.map((item, index) => {
                  const count = learning.progress[overlay.course.id] ?? 0;
                  const done = index < count;
                  const current = index === count;
                  return (
                    <li
                      key={item}
                      className={
                        done ? "is-complete" : current ? "is-current" : ""
                      }
                    >
                      <span className="v2-module-status">
                        {done ? (
                          <Check size={16} />
                        ) : current ? (
                          <Play size={13} fill="currentColor" />
                        ) : (
                          <LockKeyhole size={14} />
                        )}
                      </span>
                      <div>
                        <strong>{item}</strong>
                        <small>
                          {done
                            ? "Completed"
                            : current
                              ? "Ready to continue"
                              : "Complete the previous module first"}
                        </small>
                      </div>
                      {current && (
                        <span className="v2-badge v2-badge--gold">Up next</span>
                      )}
                    </li>
                  );
                })}
              </ol>
              <p className="v2-form-note">
                Preview lesson controls: completing a module updates this course
                and the annual CPD tracker. Lesson content is not included in
                this design demo.
              </p>
              <div className="v2-workspace__actions">
                <a
                  href={brochureFor(overlay.course)}
                  download
                  className="v2-text-link"
                >
                  <ArrowDownToLine size={16} /> Course materials
                </a>
                <button
                  type="button"
                  className="v2-button v2-button--gold"
                  disabled={
                    (learning.progress[overlay.course.id] ?? 0) >=
                    overlay.course.modules.length
                  }
                  onClick={() => {
                    learning.completeNext(overlay.course.id);
                    toast(
                      "Module complete. Your learning progress and CPD hours are updated.",
                    );
                  }}
                >
                  {(learning.progress[overlay.course.id] ?? 0) >=
                  overlay.course.modules.length ? (
                    <>
                      <CheckCheck size={17} /> Programme complete
                    </>
                  ) : (
                    <>
                      Complete next module <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
          {overlay.type === "trainer" && (
            <div className="v2-trainer-detail">
              <Avatar trainer={overlay.trainer} />
              <h3>{overlay.trainer.name}</h3>
              <p className="v2-faculty-role">{overlay.trainer.role}</p>
              <span className="v2-trainer-credentials">
                {overlay.trainer.credentials}
              </span>
              <p>{overlay.trainer.bio}</p>
              <h4>
                Programmes with{" "}
                {overlay.trainer.name.split(" ")[0] === "Dr."
                  ? "Dr. Vance"
                  : overlay.trainer.name.split(" ")[0]}
              </h4>
              <div className="v2-trainer-programmes">
                {COURSES.filter(
                  (course) => course.trainerId === overlay.trainer.id,
                ).map((course) => (
                  <button
                    type="button"
                    key={course.id}
                    onClick={() => setOverlay({ type: "course", course })}
                  >
                    <span>
                      {course.title}
                      <small>
                        {course.duration} · {course.hours} CPD hrs
                      </small>
                    </span>
                    <ArrowUpRight size={17} />
                  </button>
                ))}
              </div>
              <small className="v2-form-note">
                Illustrative faculty profile supplied for design review.
              </small>
            </div>
          )}
          {overlay.type === "cpd" && (
            <div className="v2-cpd-detail">
              <p>Annual learning goal</p>
              <strong className="v2-cpd-detail__total">
                {learning.hours}
                <span> / 60 hours</span>
              </strong>
              <ProgressBar
                value={(learning.hours / 60) * 100}
                label="CPD annual total"
              />
              <div className="v2-cpd-ledger">
                {enrolled.map((course) => (
                  <div key={course.id}>
                    <span>
                      {course.title}
                      <small>
                        {learning.progress[course.id]} completed modules
                      </small>
                    </span>
                    <strong>
                      {(learning.progress[course.id] / course.modules.length) *
                        course.hours}{" "}
                      hrs
                    </strong>
                  </div>
                ))}
              </div>
              <p className="v2-form-note">
                Sample CPD information for review. This preview does not issue
                accredited credits or certificates.
              </p>
              <button
                type="button"
                className="v2-button v2-button--gold"
                onClick={() => {
                  setOverlay(null);
                  navigate("learning");
                }}
              >
                Go to my learning <ArrowRight size={16} />
              </button>
            </div>
          )}
          {overlay.type === "account" && (
            <div className="v2-account-detail v2-guest-prompt">
              <span className="v2-guest-icon">
                <UserRound size={28} />
              </span>
              <h3>{seeker ? displayName : "Your next chapter starts here."}</h3>
              <p>
                {seeker
                  ? seeker.email
                  : "Join FinEx Careers to enrol in courses, save your learning and track your progress from the beginning."}
              </p>
              {seeker ? (
                <>
                  <span className="v2-badge v2-badge--gold">
                    {member
                      ? "Verified FinEx Club member"
                      : "Club membership not linked"}
                  </span>
                  <dl>
                    <div>
                      <dt>Enrolled programmes</dt>
                      <dd>{enrolled.length}</dd>
                    </div>
                    <div>
                      <dt>Learning hours earned</dt>
                      <dd>{learning.hours}</dd>
                    </div>
                  </dl>
                  {!member && (
                    <p className="v2-form-note">
                      Member workshops require verified FinEx Club membership.
                      Contact the Club to link your membership.
                    </p>
                  )}
                  <Link to="/account" className="v2-button v2-button--outline">
                    Manage account <ArrowUpRight size={15} />
                  </Link>
                </>
              ) : (
                <div className="v2-guest-actions">
                  <Link
                    className="v2-button v2-button--gold"
                    to="/register"
                    state={{ from: "/learning" }}
                  >
                    Create free account <ArrowRight size={16} />
                  </Link>
                  <Link
                    className="v2-button v2-button--outline"
                    to="/signin"
                    state={{ from: "/learning" }}
                  >
                    Already have an account? Sign in
                  </Link>
                </div>
              )}
            </div>
          )}
        </PreviewDialog>
      )}
    </div>
  );
}

function CourseCard({
  course,
  member,
  progress,
  onSummary,
  onOpen,
  onTrainer,
  onAction,
}: {
  course: PreviewCourse;
  member: boolean;
  progress: number | undefined;
  onSummary: () => void;
  onOpen: () => void;
  onTrainer: () => void;
  onAction: () => void;
}) {
  const trainer = trainerFor(course);
  const percentage =
    progress === undefined
      ? 0
      : Math.round((progress / course.modules.length) * 100);
  return (
    <article
      className="v2-course-card is-clickable"
      onClick={(event) => {
        // The whole card opens the course; its own buttons and links keep their actions.
        if (!(event.target as HTMLElement).closest("a, button, input, label")) onOpen();
      }}
    >
      <div className="v2-course-card__top">
        <span className={`v2-category v2-category--${trainer.tone}`}>
          {course.category}
        </span>
        <span className="v2-rating">
          <Star size={13} fill="currentColor" /> {course.rating}
          <small>({course.reviews})</small>
        </span>
      </div>
      <h3>
        {FULL_COURSES.has(course.id) ? (
          <Link className="v2-course-title-link" to={`/learning/courses/${course.id}`}>
            {course.title}
          </Link>
        ) : (
          course.title
        )}
      </h3>
      <p className="v2-course-description">{course.description}</p>
      <div className="v2-course-facts">
        <span>
          <Clock3 size={14} /> {course.duration}
        </span>
        <span>
          <Award size={14} /> {course.hours} CPD hrs
        </span>
        <span>{course.level}</span>
      </div>
      <button type="button" className="v2-course-trainer" onClick={onTrainer}>
        <Avatar trainer={trainer} small />
        <span>
          <strong>{trainer.name}</strong>
          <small>{trainer.role}</small>
        </span>
        <ArrowUpRight size={14} />
      </button>
      <div className="v2-course-price">
        <div>
          <strong>{money(member ? course.price : course.fullPrice)}</strong>
          {member && <s>{money(course.fullPrice)}</s>}
          <small>
            {member ? (
              <>
                Member price <span>· Save 20%</span>
              </>
            ) : (
              <>
                Member price <span>{money(course.price)}</span>
              </>
            )}
          </small>
        </div>
        <span className="v2-course-format">
          Online
          <br />
          <strong>At your pace</strong>
        </span>
      </div>
      {progress !== undefined ? (
        <div className="v2-course-progress">
          <div>
            <span>
              {percentage === 100
                ? "Programme complete"
                : "Your learning progress"}
            </span>
            <strong>{percentage}%</strong>
          </div>
          <ProgressBar value={percentage} label={`${course.title} progress`} />
        </div>
      ) : (
        <p className="v2-course-availability">
          <span className="v2-status-dot" /> Enrolment open{" "}
          <span>· Starts 23 Nov</span>
        </p>
      )}
      <div className="v2-course-links">
        <a href={brochureFor(course)} download>
          <ArrowDownToLine size={15} /> Brochure
        </a>
        <button type="button" onClick={onSummary}>
          <BookOpen size={15} /> Course summary
        </button>
      </div>
      <button
        type="button"
        className={`v2-course-cta${progress !== undefined ? " is-enrolled" : ""}`}
        onClick={onAction}
      >
        {progress !== undefined ? (
          <>
            <Play size={13} fill="currentColor" />{" "}
            {percentage === 100 ? "Review programme" : "Continue learning"}{" "}
            <ArrowRight size={16} />
          </>
        ) : (
          <>
            Enrol now <ArrowRight size={16} />
          </>
        )}
      </button>
    </article>
  );
}
