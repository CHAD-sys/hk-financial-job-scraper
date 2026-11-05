import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

/** Admin-only preview routes: anyone else is sent to the public Learning page. */
export default function AdminOnly({ children }: { children: ReactNode }) {
  const { seeker, loading } = useAuth();
  if (loading) return <main className="route-loading" aria-busy="true" />;
  return seeker?.is_admin ? <>{children}</> : <Navigate to="/learning" replace />;
}
