import { useEffect, useState } from "react";
import { COURSES, WORKSHOPS } from "./catalogue";

interface WorkspaceState {
  progress: Record<string, number>;
  reservations: string[];
}
const empty = (): WorkspaceState => ({ progress: {}, reservations: [] });

// Each actual Seeker starts empty. The previous seeded demo key is never read.
function restore(seekerId: string | null): WorkspaceState {
  if (!seekerId) return empty();
  try {
    const parsed: unknown = JSON.parse(
      localStorage.getItem(`finex-learning-workspace-v3:${seekerId}`) ?? "null",
    );
    if (!parsed || typeof parsed !== "object") return empty();
    const value = parsed as { progress?: unknown; reservations?: unknown };
    if (
      !value.progress ||
      typeof value.progress !== "object" ||
      Array.isArray(value.progress)
    )
      return empty();
    const progress: Record<string, number> = {};
    for (const [id, count] of Object.entries(value.progress)) {
      const course = COURSES.find((item) => item.id === id);
      if (
        course &&
        typeof count === "number" &&
        Number.isInteger(count) &&
        count >= 0 &&
        count <= course.modules.length
      )
        progress[id] = count;
    }
    const reservations = Array.isArray(value.reservations)
      ? value.reservations.filter(
          (id): id is string =>
            typeof id === "string" && WORKSHOPS.some((item) => item.id === id),
        )
      : [];
    return { progress, reservations };
  } catch {
    return empty();
  }
}

export function useLearningWorkspace(seekerId: string | null) {
  const [stored, setStored] = useState(() => ({
    owner: seekerId,
    data: restore(seekerId),
  }));
  const [persistent, setPersistent] = useState(true);
  const state = stored.owner === seekerId ? stored.data : restore(seekerId);
  useEffect(() => {
    if (stored.owner !== seekerId) {
      setStored({ owner: seekerId, data: restore(seekerId) });
      return;
    }
    if (!seekerId) return;
    try {
      localStorage.setItem(
        `finex-learning-workspace-v3:${seekerId}`,
        JSON.stringify(stored.data),
      );
      setPersistent(true);
    } catch {
      setPersistent(false);
    }
  }, [seekerId, stored]);
  const enrol = (id: string) => {
    if (!seekerId) return;
    setStored((previous) => {
      const data =
        previous.owner === seekerId ? previous.data : restore(seekerId);
      return {
        owner: seekerId,
        data: {
          ...data,
          progress: { ...data.progress, [id]: data.progress[id] ?? 0 },
        },
      };
    });
  };
  const completeNext = (id: string) => {
    if (!seekerId) return;
    setStored((previous) => {
      const course = COURSES.find((item) => item.id === id);
      if (
        !course ||
        previous.owner !== seekerId ||
        !(id in previous.data.progress)
      )
        return previous;
      return {
        ...previous,
        data: {
          ...previous.data,
          progress: {
            ...previous.data.progress,
            [id]: Math.min(
              course.modules.length,
              previous.data.progress[id] + 1,
            ),
          },
        },
      };
    });
  };
  const reserve = (id: string) => {
    if (!seekerId) return;
    setStored((previous) => {
      const data =
        previous.owner === seekerId ? previous.data : restore(seekerId);
      return {
        owner: seekerId,
        data: {
          ...data,
          reservations: data.reservations.includes(id)
            ? data.reservations
            : [...data.reservations, id],
        },
      };
    });
  };
  const hours = COURSES.reduce(
    (sum, course) =>
      sum +
      ((state.progress[course.id] ?? 0) / course.modules.length) * course.hours,
    0,
  );
  return { ...state, enrol, completeNext, reserve, hours, persistent };
}
