import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Award,
  BookOpen,
  Check,
  CheckCircle2,
  CircleHelp,
  Clock3,
  FileText,
  FlaskConical,
  GraduationCap,
  LockKeyhole,
  Play,
  Unlock,
  Users,
  X,
} from "lucide-react";
import { brochureFor, money, summaryFor, trainerFor } from "../catalogue";
import { fetchMyLearning } from "../../api/client";
import { QUANT_LESSON_COUNT, QUANT_MODULES, QUANT_OVERVIEW } from "./quant";
import { COURSE_ITEMS, useQuantCourse } from "./useQuantCourse";
import "./course-page.css";

const SECTIONS = [
  ["overview", "Overview"],
  ["curriculum", "Curriculum"],
  ["capstone", "Capstone"],
  ["faculty", "Faculty"],
  ["readings", "Readings"],
  ["fees", "Fees"],
] as const;

export default function CoursePage() {
  const { courseId } = useParams();
  const c = useQuantCourse(courseId);
  const { course, seeker, learning, enrolled, completed, reviewAll } = c;
  const [member, setMember] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!seeker) return;
    let active = true;
    fetchMyLearning()
      .then((record) => active && setMember(record.member))
      .catch(() => active && setMember(false));
    return () => {
      active = false;
    };
  }, [seeker]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [courseId]);

  // Only the quant programme has full content so far.
  if (!course) return <Navigate to="/learning" replace />;

  const trainer = trainerFor(course);
  // Where "continue" goes: the first unfinished step of the current week.
  const resume =
    COURSE_ITEMS.find((it) => it.week === Math.min(completed + 1, QUANT_MODULES.length) && !c.itemDone(it)) ??
    COURSE_ITEMS.find((it) => it.week === Math.min(completed + 1, QUANT_MODULES.length))!;
  const percent = Math.round((completed / course.modules.length) * 100);

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3600);
  }
  function enrol() {
    learning.enrol(course!.id);
    flash("You are enrolled. Start Week 1 whenever you are ready.");
  }

  const enrolAction = !seeker ? (
    <Link className="v2-button v2-button--gold cp-cta" to="/register" state={{ from: `/learning/courses/${course.id}` }}>
      Create account to enrol <ArrowRight size={16} />
    </Link>
  ) : enrolled ? (
    <Link className="v2-button v2-button--gold cp-cta" to={c.learnPath(resume)}>
      <Play size={13} fill="currentColor" /> {percent === 100 ? "Review programme" : completed === 0 ? "Start week 1" : "Continue learning"}
    </Link>
  ) : (
    <button type="button" className="v2-button v2-button--gold cp-cta" onClick={enrol}>
      Enrol now <ArrowRight size={16} />
    </button>
  );

  return (
    <div className="cp">
      <div className="v2-container">
        {reviewAll && (
          <p className="cp-review-banner" role="status">
            Review mode: every week is unlocked. Open any lesson from the curriculum to read it in the course player.
          </p>
        )}
        <nav className="cp-crumbs" aria-label="Breadcrumb">
          <Link to="/learning">
            <ArrowLeft size={14} /> Learning
          </Link>
          <span>/</span>
          <span>{course.category}</span>
        </nav>

        <header className="cp-hero">
          <div className="cp-hero__copy">
            <span className="v2-category v2-category--blue">{course.category}</span>
            <h1>{course.title}</h1>
            <p className="cp-hero__tagline">{QUANT_OVERVIEW.tagline}</p>
            <ul className="cp-hero__facts">
              <li><Clock3 size={15} /> {course.duration} · ≈6 h/week</li>
              <li><Award size={15} /> {course.hours} CPD hours</li>
              <li><GraduationCap size={15} /> {course.level}</li>
              <li><Unlock size={15} /> Week 1 free to preview</li>
            </ul>
            <div className="cp-hero__actions">
              {enrolAction}
              {!enrolled && (
                <Link className="v2-button v2-button--outline" to={c.learnPath(COURSE_ITEMS[0])}>
                  <Unlock size={15} /> Try week 1 free
                </Link>
              )}
              <a className="v2-button v2-button--outline" href={brochureFor(course)} download>
                <ArrowDownToLine size={15} /> Brochure
              </a>
              <a className="v2-button v2-button--outline" href={summaryFor(course.id)} download>
                <FileText size={15} /> Course summary
              </a>
            </div>
          </div>

          <aside className="cp-panel" aria-label="Enrolment">
            <div className="cp-panel__price">
              <span>{member ? "Member price" : "Programme fee"}</span>
              <strong>{money(member ? course.price : course.fullPrice)}</strong>
              {!member && <small>Members pay {money(course.price)} · save 20%</small>}
            </div>
            {enrolled ? (
              <div className="cp-panel__progress">
                <div>
                  <span>Your progress</span>
                  <strong>{percent}%</strong>
                </div>
                <div className="v2-progress" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Course progress">
                  <span style={{ transform: `scaleX(${percent / 100})` }} />
                </div>
                <small>
                  {completed} of {course.modules.length} weeks complete · {((completed / course.modules.length) * course.hours).toFixed(0)} CPD hours earned
                </small>
              </div>
            ) : (
              <p className="cp-panel__cohort">
                <span className="v2-status-dot" /> Next cohort starts <strong>23 November 2026</strong>
              </p>
            )}
            <ul className="cp-panel__list">
              <li><Check size={15} /> {QUANT_MODULES.length} weeks · {QUANT_LESSON_COUNT} lessons</li>
              <li><Check size={15} /> 5 Python labs on real Asia-Pacific data, auto-checked</li>
              <li><Check size={15} /> 8 interactive models you can experiment with</li>
              <li><Check size={15} /> Live Tuesday sessions, 7:00–8:30 pm HKT</li>
              <li><Check size={15} /> Capstone reviewed by a practitioner panel</li>
              <li><Check size={15} /> {course.hours} CPD hours · certificate of completion</li>
            </ul>
            {enrolAction}
          </aside>
        </header>
      </div>

      <nav className="cp-tabs" aria-label="Course sections">
        <div className="v2-container">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </div>
      </nav>

      <div className="v2-container cp-body">
        <section id="overview" className="cp-section">
          <SectionTitle eyebrow="Overview" title="Why this programme" />
          <div className="cp-overview">
            <div className="cp-prose">
              {QUANT_OVERVIEW.intro.map((p) => (
                <p key={p.slice(0, 20)}>{p}</p>
              ))}
            </div>
            <dl className="cp-format">
              {QUANT_OVERVIEW.format.map((item) => (
                <div key={item.label}>
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <h3 className="cp-subhead">What you will be able to do</h3>
          <ol className="cp-outcomes">
            {QUANT_OVERVIEW.outcomes.map((item, i) => (
              <li key={item}>
                <span>{String(i + 1).padStart(2, "0")}</span>
                {item}
              </li>
            ))}
          </ol>

          <div className="cp-two">
            <div>
              <h3 className="cp-subhead"><Users size={17} /> Who it is for</h3>
              <ul className="cp-ticks">
                {QUANT_OVERVIEW.audience.map((item) => (
                  <li key={item}><Check size={15} /> {item}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="cp-subhead"><BookOpen size={17} /> Before you start</h3>
              <ul className="cp-ticks">
                {QUANT_OVERVIEW.prerequisites.map((item) => (
                  <li key={item}><Check size={15} /> {item}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section id="curriculum" className="cp-section">
          <SectionTitle
            eyebrow="Curriculum"
            title="Six weeks, module by module"
            aside={`${QUANT_LESSON_COUNT} lessons · ${course.hours} CPD hours`}
          />
          <ol className="cp-outline">
            {QUANT_MODULES.map((module) => {
              const status = c.statusOf(module);
              const unlocked = c.isOpen(module);
              const items = COURSE_ITEMS.filter((it) => it.week === module.week);
              const done = items.filter(c.itemDone).length;
              return (
                <li key={module.week} className={`cp-outline__week is-${status}`}>
                  <div className="cp-outline__head">
                    <span className="cp-module__week">
                      {status === "done" ? <Check size={16} /> : unlocked ? `W${module.week}` : <LockKeyhole size={14} />}
                    </span>
                    <div>
                      <strong>{module.title}</strong>
                      <small>{module.hook}</small>
                    </div>
                    <div className="cp-outline__cta">
                      {status === "free" && module.free && <em className="v2-badge v2-badge--green">Free preview</em>}
                      {status === "done" && <em className="v2-badge v2-badge--green">Complete</em>}
                      {status === "current" && <em className="v2-badge v2-badge--gold">{done}/{items.length} done</em>}
                      {unlocked ? (
                        <Link className="v2-button v2-button--outline" to={c.learnPath(items.find((it) => !c.itemDone(it)) ?? items[0])}>
                          {status === "done" ? "Review" : done ? "Continue" : "Start"} <ArrowRight size={14} />
                        </Link>
                      ) : (
                        <span className="cp-outline__locked">
                          <LockKeyhole size={13} /> {status === "locked" ? `After week ${module.week - 1}` : "Enrol to unlock"}
                        </span>
                      )}
                    </div>
                  </div>
                  <ul className="cp-outline__items">
                    {items.map((it) => {
                      const Icon = it.kind === "lesson" ? BookOpen : it.kind === "check" ? CircleHelp : FlaskConical;
                      const label = (
                        <>
                          {c.itemDone(it) ? <Check size={14} className="is-done" /> : <Icon size={14} />}
                          <span>{it.title}</span>
                          {it.minutes && <small>{it.minutes} min</small>}
                        </>
                      );
                      return (
                        <li key={it.item}>
                          {unlocked ? <Link to={c.learnPath(it)}>{label}</Link> : <span>{label}</span>}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ol>
        </section>

        <section id="capstone" className="cp-section">
          <SectionTitle eyebrow="Capstone" title={QUANT_OVERVIEW.capstone.title} />
          <div className="cp-capstone">
            <div>
              <p className="cp-lead">{QUANT_OVERVIEW.capstone.brief}</p>
              <h3 className="cp-subhead">You will submit</h3>
              <ul className="cp-ticks">
                {QUANT_OVERVIEW.capstone.deliverables.map((item) => (
                  <li key={item}><Check size={15} /> {item}</li>
                ))}
              </ul>
            </div>
            <div className="cp-rubric">
              <h3>How it is assessed</h3>
              {QUANT_OVERVIEW.capstone.rubric.map((row) => (
                <div key={row.item}>
                  <span>{row.item}<strong>{row.weight}%</strong></span>
                  <div className="v2-progress"><span style={{ transform: `scaleX(${row.weight / 30})` }} /></div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="faculty" className="cp-section">
          <SectionTitle eyebrow="Faculty" title="Learn from a practitioner" />
          <div className="cp-faculty">
            <span className={`v2-avatar v2-avatar--${trainer.tone}`}>{trainer.initials}</span>
            <div>
              <h3>{trainer.name}</h3>
              <p className="cp-faculty__role">{trainer.role}</p>
              <p className="cp-faculty__cred">{trainer.credentials}</p>
              <p>{trainer.bio}</p>
              <p className="cp-faculty__note">
                Capstone presentations are reviewed by a panel of portfolio managers and risk practitioners.
              </p>
            </div>
          </div>
        </section>

        <section id="readings" className="cp-section">
          <SectionTitle eyebrow="Readings" title="The research behind the programme" />
          <ol className="cp-readings">
            {QUANT_MODULES.flatMap((m) => m.readings.map((r) => ({ ...r, week: m.week }))).map((r) => (
              <li key={r.citation}>
                <span>Week {r.week}</span>
                <p>{r.citation}</p>
                <small>{r.why}</small>
              </li>
            ))}
          </ol>
        </section>

        <section id="fees" className="cp-section cp-fees">
          <div>
            <span className="cp-eyebrow">Fees & enrolment</span>
            <h2>Build portfolios you can defend.</h2>
            <p>
              Programme fee {money(course.fullPrice)} · FinEx members {money(course.price)}. Includes all live sessions, labs, datasets, capstone review and your certificate.
            </p>
          </div>
          <div className="cp-fees__actions">
            {enrolAction}
            <a className="v2-button v2-button--outline cp-fees__outline" href={brochureFor(course)} download>
              <ArrowDownToLine size={15} /> Download brochure
            </a>
          </div>
        </section>

        <p className="cp-disclaimer">
          Illustrative programme for this preview. Faculty profile, ratings, dates and fees are sample content; CPD hours are FinEx learning hours and do not imply accreditation by any regulator or professional body. Chart inputs are illustrative; the readings are real publications.
        </p>
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

function SectionTitle({ eyebrow, title, aside }: { eyebrow: string; title: string; aside?: string }) {
  return (
    <div className="cp-section__title">
      <div>
        <span className="cp-eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {aside && <span className="cp-section__aside">{aside}</span>}
    </div>
  );
}
