import { lazy } from "react";
import { useAuth } from "../auth/useAuth";

const LearningCenterPage = lazy(() => import("./LearningCenterPage"));
const LegacyLearningPage = lazy(() => import("./LegacyLearningPage"));

/**
 * /learning while the new learning centre is in admin-only preview.
 *
 * Admin accounts get the new learning centre (catalogue, course pages, course
 * player). Everyone else keeps the current public Learning page unchanged.
 * Remove this switch, and AdminOnly on the course routes, to launch publicly.
 */
export default function LearningPage() {
  const { seeker, loading } = useAuth();
  if (loading) return <main className="route-loading" aria-busy="true" />;
  return seeker?.is_admin ? <LearningCenterPage /> : <LegacyLearningPage />;
}
