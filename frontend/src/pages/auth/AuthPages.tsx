// Sign in, sign up and password reset. Supabase does the work; these are the screens.

import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { Brand } from "../../components/Layout";
import { FormError, Icon, PasswordField, Spinner } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { publicConfig, supabase } from "../../lib/supabase";

const SAMPLE_AREAS: [string, string, string][] = [["Visuospatial", "#1b7aaf", "80%"], ["Attention", "#f5b841", "67%"], ["Language", "#22a699", "100%"], ["Orientation", "#5bb8e6", "83%"]];

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="auth-shell">
      <aside className="auth-side">
        <Brand to="/" />
        <div className="auth-pitch">
          <div>
            <h1>Cognitive screening, <span className="grad-text">made human.</span></h1>
            <p>Take the Montreal Cognitive Assessment by voice and camera, then get your result from a real examiner.</p>
          </div>
          <div className="auth-show" aria-hidden="true">
            <div className="auth-panel">
              <div className="eyebrow">Example result</div>
              <div className="auth-bars">
                {SAMPLE_AREAS.map(([name, c, w]) => (
                  <div className="auth-bar" key={name}><span>{name}</span><i style={{ "--c": c, "--w": w } as React.CSSProperties} /></div>
                ))}
              </div>
            </div>
            <div className="float-card b"><span className="float-ico"><Icon name="check" /></span><span><b>Reviewed</b><small>by your examiner</small></span></div>
          </div>
          <ul className="auth-points">
            <li><Icon name="mic" /> Answer by voice</li>
            <li><Icon name="shield" /> Checked by an examiner</li>
            <li><Icon name="check" /> Private to you</li>
          </ul>
        </div>
      </aside>
      <main className="auth-main"><div className="auth-card">{children}</div></main>
    </div>
  );
}

function GoogleButton() {
  if (!publicConfig.google_login) return null;
  const go = () => supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: location.origin } });
  return (
    <>
      <button type="button" className="btn" onClick={go}>Continue with Google</button>
      <div className="divider">or</div>
    </>
  );
}

const MIN_PASSWORD = 8;

function friendly(message: string) {
  if (/invalid login/i.test(message)) return "That email and password don't match.";
  if (/not confirmed/i.test(message)) return "Please confirm your email first: check your inbox for the link.";
  return message;
}

export function Login() {
  const { session, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";

  if (loading) return <Spinner />;
  if (session && !busy) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setError(friendly(error.message));
      setBusy(false);
    } else navigate(from, { replace: true });
  };

  return (
    <AuthShell>
      <h2>Welcome back</h2>
      <p className="muted" style={{ margin: 0 }}>Sign in to your tests and results.</p>
      <GoogleButton />
      <form onSubmit={submit}>
        <label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <PasswordField label="Password" autoComplete="current-password" value={password} onChange={setPassword} />
        <FormError error={error} />
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <div className="auth-links"><Link to="/forgot-password">Forgot password?</Link><Link to="/signup">Create an account</Link></div>
    </AuthShell>
  );
}

export function Signup() {
  const { session, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const navigate = useNavigate();

  if (loading) return <Spinner />;
  if (session && !busy) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters for your password.`);
    setBusy(true);
    setError(null);
    const { data, error } = await supabase.auth.signUp({
      email, password, options: { emailRedirectTo: `${location.origin}/onboarding` },
    });
    setBusy(false);
    if (error) setError(friendly(error.message));
    else if (data.session) navigate("/onboarding", { replace: true });
    else setSent(true);                  // the project asks for email confirmation first
  };

  if (sent) {
    return (
      <AuthShell>
        <h2>Check your email</h2>
        <p className="muted">We sent a link to <b>{email}</b>. Open it to confirm your address and finish setting up.</p>
        <Link to="/login">Back to sign in</Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <h2>Create your account</h2>
      <p className="muted" style={{ margin: 0 }}>For patients taking a test. If your examiner sent you a link, open that instead.</p>
      <GoogleButton />
      <form onSubmit={submit}>
        <label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <PasswordField label="Password" minLength={MIN_PASSWORD} autoComplete="new-password" value={password} onChange={setPassword} />
        <FormError error={error} />
        <button className="btn primary" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      </form>
      <div className="auth-links"><span className="muted">Already have an account?</span><Link to="/login">Sign in</Link></div>
    </AuthShell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${location.origin}/reset-password` });
    if (error) setError(friendly(error.message));
    else setSent(true);
  };

  return (
    <AuthShell>
      <h2>Reset your password</h2>
      {sent
        ? <p className="muted">If <b>{email}</b> has an account, a reset link is on its way.</p>
        : (
          <form onSubmit={submit}>
            <label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            <FormError error={error} />
            <button className="btn primary">Send reset link</button>
          </form>
        )}
      <Link to="/login">Back to sign in</Link>
    </AuthShell>
  );
}

export function ResetPassword() {
  const { session, loading } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  if (loading) return <Spinner />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) return setError(`Use at least ${MIN_PASSWORD} characters for your password.`);
    const { error } = await supabase.auth.updateUser({ password });
    if (error) setError(friendly(error.message));
    else navigate("/", { replace: true });
  };

  return (
    <AuthShell>
      <h2>Choose a new password</h2>
      {session
        ? (
          <form onSubmit={submit}>
            <PasswordField label="New password" minLength={MIN_PASSWORD} autoComplete="new-password" value={password} onChange={setPassword} />
            <FormError error={error} />
            <button className="btn primary">Save password</button>
          </form>
        )
        : <><p className="muted">This link has expired or was already used.</p><Link to="/forgot-password">Send a new link</Link></>}
    </AuthShell>
  );
}
