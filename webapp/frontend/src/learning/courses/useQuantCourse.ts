import { useSearchParams } from "react-router-dom";
import { COURSES } from "../catalogue";
import { useLearningWorkspace } from "../useLearningWorkspace";
import { useAuth } from "../../auth/useAuth";
import { QUANT_MODULES, QUANT_OVERVIEW, type CourseModule } from "./quant";
import { useCourseProgress } from "./useCourseProgress";

/** `open`: an enrolled learner's later week, readable and trackable before the current week is finished. */
export type WeekStatus = "free" | "preview" | "done" | "current" | "open" | "locked";
export type ItemId = `${number}` | "check" | "lab";
export interface CourseItem {
  week: number;
  item: ItemId;
  kind: "lesson" | "check" | "lab";
  title: string;
  minutes?: number;
}

/** Every step of the course in order: each week's lessons, its check, then its lab. */
export const COURSE_ITEMS: CourseItem[] = QUANT_MODULES.flatMap((module) => [
  ...module.lessons.map((lesson, i) => ({
    week: module.week,
    item: `${i + 1}` as ItemId,
    kind: "lesson" as const,
    title: lesson.title,
    minutes: lesson.minutes,
  })),
  { week: module.week, item: "check" as const, kind: "check" as const, title: "Knowledge check" },
  {
    week: module.week,
    item: "lab" as const,
    kind: "lab" as const,
    title: module.week === QUANT_MODULES.length ? "Capstone submission" : module.lab.title.replace(/^Lab \d · /, "Lab · "),
  },
]);

/** Enrolment, progress and what this viewer may open, shared by the overview and the player. */
export function useQuantCourse(courseId: string | undefined) {
  const { seeker } = useAuth();
  const learning = useLearningWorkspace(seeker?.id ?? null);
  const progress = useCourseProgress(seeker?.id ?? null, courseId ?? "");
  const [search] = useSearchParams();
  // Review mode: admins, or ?preview=all on a local dev server, see every week unlocked.
  const previewParam = import.meta.env.DEV && search.get("preview") === "all";
  const reviewAll = !!seeker?.is_admin || previewParam;
  const course = COURSES.find((item) => item.id === courseId && item.id === QUANT_OVERVIEW.id);
  const enrolled = !!course && course.id in learning.progress;
  const completed = course ? learning.progress[course.id] ?? 0 : 0;

  function statusOf(module: CourseModule): WeekStatus {
    const index = module.week - 1;
    if (enrolled) {
      if (index < completed) return "done";
      if (index === completed) return "current";
      return "open"; // enrolled learners can read ahead; only week completion is in order
    }
    return module.free || reviewAll ? "free" : "preview";
  }
  const isOpen = (module: CourseModule) => ["free", "done", "current", "open"].includes(statusOf(module));
  const isTracking = (module: CourseModule) => ["done", "current", "open"].includes(statusOf(module));
  const itemDone = (it: CourseItem) =>
    it.kind === "lesson"
      ? progress.lessonDone(`${it.week}.${it.item}`)
      : it.kind === "check"
        ? progress.checkDone(it.week)
        : progress.labDone(it.week) || it.week <= completed;
  /** Keep ?preview=all on internal links so review mode survives navigation. */
  const link = (path: string) => (previewParam ? `${path}?preview=all` : path);
  const learnPath = (it: Pick<CourseItem, "week" | "item">) => link(`/learning/courses/${QUANT_OVERVIEW.id}/learn/${it.week}/${it.item}`);

  return {
    seeker, learning, progress, course, enrolled, completed, reviewAll,
    statusOf, isOpen, isTracking, itemDone, link, learnPath,
  };
}
