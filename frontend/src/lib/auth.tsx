// Who is signed in: the Supabase session plus the app's own record (role and profile).

import type { Session } from "@supabase/supabase-js";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { supabase } from "./supabase";
import type { ExaminerProfile, Me, PatientProfile } from "./types";

interface Auth {
  session: Session | null;
  me: Me | null;
  loading: boolean;
  /** True after a "reset password" email link: the next page sets a new one. */
  recovering: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const queries = useQueryClient();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((event, next) => {
      setSession(next);
      if (event === "PASSWORD_RECOVERY") setRecovering(true);
      if (event === "SIGNED_OUT") {
        setRecovering(false);
        queries.clear();                 // nothing of this user stays in memory
      }
    });
    return () => data.subscription.unsubscribe();
  }, [queries]);

  const userId = session?.user.id;
  const me = useQuery({
    queryKey: ["me", userId],
    queryFn: () => api<Me>("/api/me"),
    enabled: !!userId,
  });

  const value = useMemo<Auth>(() => ({
    session,
    me: me.data ?? null,
    loading: !ready || (!!userId && me.isLoading),
    recovering,
    signOut: async () => { await supabase.auth.signOut(); },
  }), [session, me.data, me.isLoading, ready, userId, recovering]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth needs an AuthProvider");
  return auth;
}

export const patientProfile = (me: Me | null) => me?.profile as PatientProfile | undefined;
export const examinerProfile = (me: Me | null) => me?.profile as ExaminerProfile | undefined;
