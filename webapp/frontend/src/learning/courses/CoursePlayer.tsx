import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  FlaskConical,
  ListTree,
  LockKeyhole,
  X,
} from "lucide-react";
import { QUANT_MODULES, QUANT_OVERVIEW } from "./quant";
import { COURSE_ITEMS, useQuantCourse, type CourseItem } from "./useQuantCourse";
import { CapstonePanel, KnowledgeCheckCard, LabPanel, LessonArticle } from "./CourseParts";
import "./course-page.css";
import "./course-player.css";

const ICONS = { lesson: BookOpen, check: CircleHelp, lab: FlaskConical };

export default function CoursePlayer() {
  const { courseId, week, item } = useParams();
  const c = useQuantCourse(courseId);
  const navigate = useNavigate();
  const [notice, setNotice] = useState("");
  const [capstoneSent, setCapstoneSent] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    window.scrollTo(0, 0);
    setMenuOpen(false);
  }, [week, item]);

  if (!c.course) return <Navigate to="/learning" replace />;
  const index = COURSE_ITEMS.findIndex((it) => String(it.week) === week && it.item === item);
  if (index < 0) return <Navigate to={c.learnPath(COURSE_ITEMS[0])} replace />;

  const current = COURSE_ITEMS[index];
  const module = QUANT_MODULES[current.week - 1];
  const status = c.statusOf(module);
  const open = c.isOpen(module);
  const tracking = c.isTracking(module);
  const previous = COURSE_ITEMS[index - 1];
  const next = COURSE_ITEMS[index + 1];
  const overview = c.link(`/learning/courses/${QUANT_OVERVIEW.id}`);
  const capstone = module.week === QUANT_MODULES.length;
  const weekItems = COURSE_ITEMS.filter((it) => it.week === module.week);
  const lessonsDone = module.lessons.filter((_, i) => c.progress.lessonDone(`${module.week}.${i + 1}`)).length;
  const requirements = [
    { label: `Lessons ${lessonsDone}/${module.lessons.length}`, done: lessonsDone === module.lessons.length },
    { label: "Knowledge check", done: c.progress.checkDone(module.week) },
    capstone
      ? { label: "Capstone submitted", done: capstoneSent }
      : { label: "Lab code", done: c.progress.labDone(module.week) },
  ];
  const percent = Math.round((c.completed / QUANT_MODULES.length) * 100);

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3600);
  }
  function go(target: CourseItem | undefined) {
    navigate(target ? c.learnPath(target) : overview);
  }
  function completeWeek() {
    c.learning.completeNext(c.course!.id);
    flash(`Week ${module.week} complete. Progress and CPD hours updated.`);
    go(next);
  }

  const lessonIndex = current.kind === "lesson" ? Number(current.item) - 1 : -1;
  const lesson = lessonIndex >= 0 ? module.lessons[lessonIndex] : null;
  const lessonId = `${module.week}.${current.item}`;

  let primary: React.ReactNode = null;
  if (open && current.kind === "lesson" && tracking && !c.progress.lessonDone(lessonId)) {
    primary = (
      <button type="button" className="v2-button v2-button--gold" onClick={() => { c.progress.completeLesson(lessonId); go(next); }}>
        Mark complete and continue <ArrowRight size={16} />
      </button>
    );
  } else if (open && current.kind === "lab" && status === "current") {
    primary = (
      <button type="button" className="v2-button v2-button--gold" disabled={!requirements.every((r) => r.done)} onClick={completeWeek}>
        Complete week {module.week} <ArrowRight size={16} />
      </button>
    );
  } else if (next) {
    primary = (
      <Link className="v2-button v2-button--gold" to={c.learnPath(next)}>
        Next <ArrowRight size={16} />
      </Link>
    );
  } else {
    primary = (
      <Link className="v2-button v2-button--gold" to={overview}>
        Back to course overview <ArrowRight size={16} />
      </Link>
    );
  }

  const eyebrow =
    current.kind === "lesson"
      ? `Week ${module.week} · Lesson ${lessonIndex + 1} of ${module.lessons.length} · ${lesson?.minutes} min`
      : current.kind === "check"
        ? `Week ${module.week} · Knowledge check`
        : `Week ${module.week} · ${capstone ? "Capstone" : "Lab"}`;
  const title = lesson?.title ?? (current.kind === "check" ? "Check your understanding" : module.lab.title);

  return (
    <div className="pl">
      <header className="pl-bar">
        <Link to={overview} className="pl-bar__back">
          <ArrowLeft size={15} /> <span>Course overview</span>
        </Link>
        <div className="pl-bar__title">
          <strong>{c.course.title}</strong>
          {c.enrolled && (
            <span className="pl-bar__progress">
              <span className="v2-progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Course progress">
                <span style={{ transform: `scaleX(${percent / 100})` }} />
              </span>
              {percent}%
            </span>
          )}
        </div>
        <button type="button" className="pl-bar__menu" onClick={() => setMenuOpen((v) => !v)} aria-expanded={menuOpen} aria-controls="pl-contents">
          {menuOpen ? <X size={17} /> : <ListTree size={17} />} Contents
        </button>
      </header>

      <div className="pl-layout">
        <nav id="pl-contents" className={`pl-side${menuOpen ? " is-open" : ""}`} aria-label="Course contents">
          {QUANT_MODULES.map((m) => {
            const s = c.statusOf(m);
            const unlocked = c.isOpen(m);
            return (
              <details key={m.week} className="pl-week" open={m.week === module.week}>
                <summary>
                  <span className={`pl-week__badge is-${s}`}>
                    {s === "done" ? <Check size={13} /> : unlocked ? m.week : <LockKeyhole size={12} />}
                  </span>
                  <span className="pl-week__title">
                    <small>Week {m.week}{s === "free" && m.free ? " · Free" : ""}</small>
                    {m.title}
                  </span>
                  <ChevronDown size={15} className="pl-week__chev" />
                </summary>
                <ol>
                  {COURSE_ITEMS.filter((it) => it.week === m.week).map((it) => {
                    const Icon = ICONS[it.kind];
                    const active = it === current;
                    const done = c.itemDone(it);
                    return (
                      <li key={it.item}>
                        <Link
                          to={c.learnPath(it)}
                          className={`pl-item${active ? " is-active" : ""}${done ? " is-done" : ""}${unlocked ? "" : " is-locked"}`}
                          aria-current={active ? "page" : undefined}
                        >
                          <span className="pl-item__icon">
                            {done ? <Check size={14} /> : unlocked ? <Icon size={14} /> : <LockKeyhole size={12} />}
                          </span>
                          <span className="pl-item__label">{it.title}</span>
                          {it.minutes && <span className="pl-item__time">{it.minutes}m</span>}
                        </Link>
                      </li>
                    );
                  })}
                </ol>
              </details>
            );
          })}
        </nav>

        <main className="pl-main">
          <article className="pl-article">
            <p className="pl-eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            {lesson && <p className="pl-lead">{lesson.summary}</p>}
            {current.kind === "lab" && !capstone && <p className="pl-lead">{module.hook}</p>}

            {!open ? (
              <div className="pl-locked">
                <LockKeyhole size={22} />
                <h2>{status === "locked" ? `Finish week ${module.week - 1} first` : "This week is for enrolled learners"}</h2>
                <p>
                  {status === "locked"
                    ? "Weeks unlock in order, once the previous week's lessons, knowledge check and lab are complete."
                    : "Enrol to unlock every lesson, lab notebook and progress tracking. Week 1 is free to preview."}
                </p>
                <Link className="v2-button v2-button--gold" to={status === "locked" ? c.learnPath(COURSE_ITEMS.find((it) => it.week === c.completed + 1) ?? COURSE_ITEMS[0]) : overview}>
                  {status === "locked" ? "Go to your current week" : "See enrolment options"} <ArrowRight size={16} />
                </Link>
              </div>
            ) : current.kind === "lesson" && lesson ? (
              <LessonArticle lesson={lesson} />
            ) : current.kind === "check" ? (
              <KnowledgeCheckCard
                key={module.week}
                check={module.check}
                passed={c.progress.checkDone(module.week)}
                onPass={tracking ? () => c.progress.passCheck(module.week) : undefined}
              />
            ) : (
              <>
                <LabPanel
                  key={module.week}
                  lab={module.lab}
                  week={module.week}
                  capstone={capstone}
                  showTitle={false}
                  tracking={tracking}
                  signedIn={!!c.seeker}
                  done={c.progress.labDone(module.week)}
                  onPass={() => { c.progress.completeLab(module.week); flash("Lab complete. Your results are unlocked."); }}
                />
                {capstone && tracking && <CapstonePanel onStatus={setCapstoneSent} onNotice={flash} />}
                <div className="cp-module__readings">
                  <strong>This week's readings</strong>
                  <ul>
                    {module.readings.map((r) => <li key={r.citation}>{r.citation}</li>)}
                  </ul>
                </div>
              </>
            )}

            {open && current.kind === "lab" && status === "current" && (
              <ul className="cp-reqs pl-reqs" aria-label={`Week ${module.week} requirements`}>
                {requirements.map((r) => (
                  <li key={r.label} className={r.done ? "is-done" : ""}>
                    {r.done ? <Check size={14} /> : <span />} {r.label}
                  </li>
                ))}
              </ul>
            )}
            {open && !c.seeker && module.free && (
              <p className="pl-note">You are previewing Week 1. Create an account and enrol to record your progress and unlock weeks 2–6.</p>
            )}

            <footer className="pl-footer">
              {previous ? (
                <Link to={c.learnPath(previous)} className="pl-footer__prev">
                  <ArrowLeft size={15} />
                  <span><small>Previous</small>{previous.title}</span>
                </Link>
              ) : <span />}
              <div className="pl-footer__next">
                {next && <small>Up next: {next.title}</small>}
                {primary}
              </div>
            </footer>
            <p className="pl-week-map">
              {weekItems.map((it) => (
                <span key={it.item} className={`${it === current ? "is-active" : ""}${c.itemDone(it) ? " is-done" : ""}`} />
              ))}
            </p>
          </article>
        </main>
      </div>

      {notice && (
        <div className="v2-toast cp-toast" role="status">
          <CheckCircle2 size={18} />
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice("")} aria-label="Dismiss">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
