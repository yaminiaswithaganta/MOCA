// The frame around every signed-in page, and the role checks on each route.

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { ExaminerProfile, PatientProfile, Role } from "../lib/types";
import { Avatar, Icon, Logo, Spinner } from "./ui";

const NAV: Record<Role, [string, string, string][]> = {
  patient: [["/patient", "My tests", "file"], ["/patient/start", "Start a test", "play"], ["/check", "Mic & camera", "mic"], ["/profile", "My details", "user"]],
  examiner: [["/examiner", "Overview", "grid"], ["/examiner/patients", "Patients", "users"], ["/examiner/tests", "Test designs", "file"], ["/profile", "My details", "user"]],
  admin: [["/admin", "People", "users"]],
};

export const homeOf = (role: Role) => `/${role}`;

function SpeechPill() {
  const { data, isError } = useQuery({
    queryKey: ["status"],
    queryFn: () => api<{ speech_ready: boolean; speech_error: string | null }>("/api/status"),
    refetchInterval: (q) => (q.state.data?.speech_ready ? false : 3000),
  });
  const [cls, text] = isError ? ["bad", "Server offline"]
    : data?.speech_ready ? ["ok", "Ready for a test"]
    : data?.speech_error ? ["bad", "Speech error"] : ["wait", "Getting ready…"];
  return <span className={`pill ${cls}`} title={data?.speech_error ?? ""}><i /><span>{text}</span></span>;
}

export function Brand({ to }: { to: string }) {
  return (
    <Link className="brand" to={to} aria-label="MoCA home">
      <Logo />
      <span className="brand-text"><b>MoCA</b><small>Cognitive assessment</small></span>
    </Link>
  );
}

export function AppLayout() {
  const { me, signOut } = useAuth();
  const role = me?.role as Role;
  const name = (me?.profile as PatientProfile | ExaminerProfile | undefined)?.name ?? me?.email ?? "";

  useEffect(() => {
    document.documentElement.dataset.role = role;
    return () => { delete document.documentElement.dataset.role; };
  }, [role]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <Brand to={homeOf(role)} />
        <nav className="nav" aria-label="Main">
          {NAV[role].map(([to, label, icon]) => <NavLink key={to} to={to} end={to === homeOf(role)}><Icon name={icon} />{label}</NavLink>)}
        </nav>
        <div className="side-foot">
          {role === "patient" && <SpeechPill />}
          <div className="side-user">
            <Avatar name={name} />
            <span className="side-who"><b>{name}</b><small>{role}</small></span>
            <button className="side-signout" onClick={signOut} aria-label="Sign out" title="Sign out"><Icon name="signout" /></button>
          </div>
        </div>
      </aside>
      <div className="shell-main">
        <main id="view"><Outlet /></main>
        <footer className="foot">A screening tool, not a diagnosis. Results are reviewed by a qualified examiner.</footer>
      </div>
    </div>
  );
}

/** Signed in with a finished account, and the right role for this part of the app. */
export function RequireRole({ role }: { role?: Role }) {
  const { session, me, loading, signOut } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!me) return <Spinner />;
  if (!me.role) return <Navigate to="/onboarding" replace />;
  if (me.deactivated) {
    return (
      <main id="view"><div className="page narrow"><div className="card">
        <h1>This account is deactivated</h1>
        <p className="muted">Please contact your clinic or administrator if you think this is a mistake.</p>
        <button className="btn" onClick={signOut}>Sign out</button>
      </div></div></main>
    );
  }
  if (role && me.role !== role) return <Navigate to={homeOf(me.role)} replace />;
  return <Outlet />;
}
