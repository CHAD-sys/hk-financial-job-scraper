import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowRight,
  Check,
  Download,
  ExternalLink,
  FlaskConical,
  Lightbulb,
  Send,
  Sigma,
} from "lucide-react";
import {
  fetchMyCapstone,
  submitCapstone,
  type CapstoneSubmission,
} from "../../api/client";
import { QUANT_OVERVIEW, type KnowledgeCheck, type Lab, type Lesson } from "./quant";
import QuantVisual from "./QuantVisuals";

const NOTEBOOKS = "/learning-assets/notebooks/quant";

/**
 * Colab can only open a notebook it can fetch itself: a public GitHub repo,
 * a public Gist or Google Drive. Set this to the public folder holding the
 * learner notebooks (e.g. "https://colab.research.google.com/github/<org>/<repo>/blob/main/quant")
 * and every lab gets a one-click "Open in Colab" button. Empty = download only.
 */
export const COLAB_BASE = "";

export function LessonArticle({ lesson }: { lesson: Lesson }) {
  return (
    <div className="cp-lesson__body">
      <div className="cp-prose">
        {lesson.body.map((p) => (
          <p key={p.slice(0, 24)}>{p}</p>
        ))}
      </div>
      {lesson.formula && (
        <div className="cp-formula">
          <span><Sigma size={15} /> {lesson.formula.label}</span>
          <code>{lesson.formula.expression}</code>
          <small>{lesson.formula.note}</small>
        </div>
      )}
      {lesson.visual && <QuantVisual id={lesson.visual} />}
      {lesson.code && (
        <div className="cp-code">
          <span>Python</span>
          <pre>
            <code>{lesson.code}</code>
          </pre>
        </div>
      )}
      <p className="cp-takeaway">
        <Lightbulb size={16} /> <span><strong>Key takeaway.</strong> {lesson.takeaway}</span>
      </p>
    </div>
  );
}

export function LabPanel({
  lab,
  week,
  capstone,
  tracking,
  signedIn,
  done,
  onPass,
  showTitle = true,
}: {
  showTitle?: boolean;
  lab: Lab;
  week: number;
  capstone: boolean;
  tracking: boolean;
  signedIn: boolean;
  done: boolean;
  onPass: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const file = `${lab.notebook}.ipynb`;
  function submit(event: FormEvent) {
    event.preventDefault();
    if (code.trim().toUpperCase() === lab.code) {
      setError("");
      onPass();
    } else {
      setError("That code does not match. Run the last cell of the notebook after every check passes.");
    }
  }
  return (
    <div className={`cp-lab${done ? " is-done" : ""}`}>
      <FlaskConical size={18} />
      <div>
        {showTitle && <strong>{lab.title}</strong>}
        <p>{lab.brief}</p>
        <small>Deliverable: {lab.deliverable}</small>
        <div className="cp-lab__actions">
          {COLAB_BASE && (
            <a className="v2-button v2-button--gold" href={`${COLAB_BASE}/${file}`} target="_blank" rel="noreferrer">
              Open in Google Colab <ExternalLink size={14} />
            </a>
          )}
          <a className="v2-button v2-button--outline" href={`${NOTEBOOKS}/${file}`} download>
            <Download size={15} /> {capstone ? "Download template notebook" : "Download notebook"}
          </a>
        </div>
        {!COLAB_BASE && (
          <details className="cp-lab__steps">
            <summary>How to open it in Google Colab</summary>
            <ol>
              <li>Download the notebook with the button above.</li>
              <li>
                Go to{" "}
                <a href="https://colab.research.google.com/" target="_blank" rel="noreferrer">colab.research.google.com</a>{" "}
                and sign in with a Google account.
              </li>
              <li>Choose <em>File → Upload notebook</em> and select <code>{file}</code>.</li>
              <li>Run the first cell. The data downloads automatically.</li>
            </ol>
            <p>Prefer your own machine? Open it in Jupyter or VS Code with Python 3.10+.</p>
          </details>
        )}
        <p className="cp-lab__how">
          The data comes from the Kenneth R. French Data Library
          {capstone ? "." : ". Each exercise is checked automatically, and the last cell prints your completion code."}
        </p>
        {!capstone && lab.code && (
          done ? (
            <div className="cp-findings">
              <span><Check size={14} /> Lab complete · what the data says</span>
              <ul>
                {lab.findings?.map((f) => <li key={f}>{f}</li>)}
              </ul>
            </div>
          ) : tracking ? (
            <form className="cp-lab__code" onSubmit={submit}>
              <label htmlFor={`lab-code-${week}`}>Completion code</label>
              <div>
                <input
                  id={`lab-code-${week}`}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder={`FINEX-LAB${week}-…`}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button type="submit" className="v2-button v2-button--gold">Submit</button>
              </div>
              {error && <small role="alert">{error}</small>}
            </form>
          ) : (
            <p className="cp-lab__how">{signedIn ? "Enrol to record your completion code." : "Create an account and enrol to record your completion code."}</p>
          )
        )}
      </div>
    </div>
  );
}

export function CapstonePanel({
  onStatus,
  onNotice,
}: {
  onStatus: (submitted: boolean) => void;
  onNotice: (message: string) => void;
}) {
  const [submission, setSubmission] = useState<CapstoneSubmission | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let active = true;
    fetchMyCapstone(QUANT_OVERVIEW.id)
      .then((value) => {
        if (!active) return;
        setSubmission(value);
        onStatus(!!value);
      })
      .catch(() => active && setSubmission(null));
    return () => {
      active = false;
    };
  }, [onStatus]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setError("");
    try {
      const saved = await submitCapstone(QUANT_OVERVIEW.id, {
        notebook_url: value("notebook_url"),
        memo_url: value("memo_url"),
        slides_url: value("slides_url") || undefined,
        note: value("note") || undefined,
      });
      setSubmission(saved);
      setEditing(false);
      onStatus(true);
      onNotice("Capstone submitted. A reviewer will add written feedback here.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit your capstone.");
    } finally {
      setBusy(false);
    }
  }

  if (submission === undefined) return <div className="cp-capstone-box"><small>Loading your submission…</small></div>;

  return (
    <div className="cp-capstone-box">
      <strong><Send size={16} /> Your capstone submission</strong>
      {submission && !editing ? (
        <>
          <dl className="cp-capstone-box__links">
            <div><dt>Notebook</dt><dd><a href={submission.notebook_url} target="_blank" rel="noreferrer">{submission.notebook_url}</a></dd></div>
            <div><dt>Memo</dt><dd><a href={submission.memo_url} target="_blank" rel="noreferrer">{submission.memo_url}</a></dd></div>
            {submission.slides_url && <div><dt>Slides</dt><dd><a href={submission.slides_url} target="_blank" rel="noreferrer">{submission.slides_url}</a></dd></div>}
            <div><dt>Submitted</dt><dd>{new Date(submission.submitted_at).toLocaleString("en-HK", { dateStyle: "medium", timeStyle: "short" })}</dd></div>
          </dl>
          {submission.feedback ? (
            <div className="cp-feedback">
              <span>Reviewer feedback · score <strong>{submission.score}/100</strong></span>
              <p>{submission.feedback}</p>
            </div>
          ) : (
            <p className="cp-lab__how">Awaiting review. Written feedback and a score will appear here.</p>
          )}
          <button type="button" className="cp-lab__colab" onClick={() => setEditing(true)}>
            Replace submission (clears any review)
          </button>
        </>
      ) : (
        <form className="cp-capstone-form" onSubmit={submit}>
          <label>Notebook link (Colab, GitHub or a shared drive)<input name="notebook_url" type="url" required placeholder="https://…" defaultValue={submission?.notebook_url} /></label>
          <label>Two-page memo link<input name="memo_url" type="url" required placeholder="https://…" defaultValue={submission?.memo_url} /></label>
          <label>Slides link (optional)<input name="slides_url" type="url" placeholder="https://…" defaultValue={submission?.slides_url ?? ""} /></label>
          <label>Note to the reviewer (optional)<textarea name="note" rows={3} maxLength={2000} defaultValue={submission?.note ?? ""} /></label>
          <p className="cp-lab__how">Make sure each link is viewable by anyone with the link.</p>
          {error && <small role="alert" className="cp-error">{error}</small>}
          <button type="submit" className="v2-button v2-button--gold" disabled={busy}>
            {busy ? "Submitting…" : "Submit capstone"} <ArrowRight size={16} />
          </button>
        </form>
      )}
    </div>
  );
}

export function KnowledgeCheckCard({
  check,
  passed,
  onPass,
}: {
  check: KnowledgeCheck;
  passed: boolean;
  onPass?: () => void;
}) {
  const [picked, setPicked] = useState<number | null>(passed ? check.answer : null);
  const correct = picked === check.answer;
  return (
    <div className="cp-check">
      <strong>Knowledge check{passed && " · passed"}</strong>
      <p>{check.question}</p>
      <div className="cp-check__options">
        {check.options.map((option, i) => (
          <button
            key={option}
            type="button"
            className={picked === null ? "" : i === check.answer && correct ? "is-right" : i === picked ? "is-wrong" : ""}
            onClick={() => {
              setPicked(i);
              if (i === check.answer) onPass?.();
            }}
            aria-pressed={picked === i}
          >
            {option}
          </button>
        ))}
      </div>
      {picked !== null && (
        <p className={`cp-check__result ${correct ? "is-right" : "is-wrong"}`} role="status">
          {correct ? `Correct. ${check.explanation}` : "Not quite. Re-read the lesson and try another answer."}
        </p>
      )}
    </div>
  );
}
