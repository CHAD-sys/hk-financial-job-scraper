import { useEffect, useState } from "react";

/**
 * Lesson-level progress inside one course: completed lessons ("week.lesson"),
 * labs whose completion code was accepted, and passed knowledge checks (by
 * week). Week completion itself stays in useLearningWorkspace, which owns the
 * catalogue progress bar and CPD hours; this hook decides when a week may be
 * completed.
 */
interface CourseProgress {
  lessons: string[];
  labs: number[];
  checks: number[];
}

const empty = (): CourseProgress => ({ lessons: [], labs: [], checks: [] });
const keyFor = (seekerId: string, courseId: string) =>
  `finex-course-progress-v1:${seekerId}:${courseId}`;

function restore(seekerId: string | null, courseId: string): CourseProgress {
  if (!seekerId) return empty();
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(keyFor(seekerId, courseId)) ?? "null");
    if (!parsed || typeof parsed !== "object") return empty();
    const value = parsed as Partial<Record<keyof CourseProgress, unknown>>;
    const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
    const numbers = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is number => Number.isInteger(x)) : []);
    return { lessons: strings(value.lessons), labs: numbers(value.labs), checks: numbers(value.checks) };
  } catch {
    return empty();
  }
}

export function useCourseProgress(seekerId: string | null, courseId: string) {
  const owner = `${seekerId}:${courseId}`;
  const [stored, setStored] = useState(() => ({ owner, data: restore(seekerId, courseId) }));
  const data = stored.owner === owner ? stored.data : restore(seekerId, courseId);

  useEffect(() => {
    if (stored.owner !== owner) {
      setStored({ owner, data: restore(seekerId, courseId) });
      return;
    }
    if (!seekerId) return;
    try {
      localStorage.setItem(keyFor(seekerId, courseId), JSON.stringify(stored.data));
    } catch {
      // Private mode or full storage: progress still works for this visit.
    }
  }, [owner, seekerId, courseId, stored]);

  function update(change: (current: CourseProgress) => CourseProgress) {
    if (!seekerId) return;
    setStored((previous) => ({
      owner,
      data: change(previous.owner === owner ? previous.data : restore(seekerId, courseId)),
    }));
  }
  const add = <T,>(list: T[], item: T) => (list.includes(item) ? list : [...list, item]);

  return {
    lessonDone: (id: string) => data.lessons.includes(id),
    labDone: (week: number) => data.labs.includes(week),
    checkDone: (week: number) => data.checks.includes(week),
    completeLesson: (id: string) => update((c) => ({ ...c, lessons: add(c.lessons, id) })),
    completeLab: (week: number) => update((c) => ({ ...c, labs: add(c.labs, week) })),
    passCheck: (week: number) => update((c) => ({ ...c, checks: add(c.checks, week) })),
  };
}
