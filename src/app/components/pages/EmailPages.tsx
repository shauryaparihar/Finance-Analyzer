import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Loader2 } from "lucide-react";
import { forgotPassword, friendlyMessage, resetPassword, verifyEmail } from "../../api";
import { MIN_PASSWORD_LENGTH } from "../../lib/validation";
import { Notice } from "../common";
import { Button } from "../ui/button";

const field = "w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/30";

function Shell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-4">
        <h1 className="text-center font-sans text-3xl tracking-tight text-primary">FinSight</h1>
        <div className="space-y-4 rounded-lg border border-border bg-card p-6">
          <h2 className="font-sans text-xl text-foreground">{title}</h2>
          {children}
        </div>
        <p className="text-center text-sm"><Link to="/login" className="text-primary underline-offset-4 hover:underline">Back to log in</Link></p>
      </div>
    </div>
  );
}

/** Ask for a reset link. The answer is the same for every address, so nobody can learn who has an account. */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) return setError("Enter your email address.");
    setBusy(true);
    setError(null);
    try {
      setDone((await forgotPassword(email.trim())).message);
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title="Reset your password">
      {done ? <Notice tone="good">{done}</Notice> : (
        <form onSubmit={submit} noValidate className="space-y-4">
          {error && <Notice tone="warn">{error}</Notice>}
          <div>
            <label htmlFor="email" className="mb-1 block text-sm text-muted-foreground">Email</label>
            <input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
          </div>
          <Button type="submit" disabled={busy} className="w-full">{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Send reset link</Button>
        </form>
      )}
    </Shell>
  );
}

/** The page the emailed link opens: choose a new password (typed twice). */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD_LENGTH) return setError(`Use at least ${MIN_PASSWORD_LENGTH} characters (you have ${password.length}).`);
    if (password !== confirm) return setError("The two passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      navigate("/login", { replace: true });
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <Shell title="Choose a new password"><Notice tone="warn">This link is incomplete. Ask for a new one from the log-in page.</Notice></Shell>;
  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} noValidate className="space-y-4">
        {error && <Notice tone="warn">{error}</Notice>}
        <div>
          <label htmlFor="password" className="mb-1 block text-sm text-muted-foreground">New password</label>
          <input id="password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
          <p className="mt-1 text-xs text-muted-foreground">At least {MIN_PASSWORD_LENGTH} characters.</p>
        </div>
        <div>
          <label htmlFor="confirm" className="mb-1 block text-sm text-muted-foreground">Confirm new password</label>
          <input id="confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={field} />
        </div>
        <Button type="submit" disabled={busy} className="w-full">{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save new password</Button>
      </form>
    </Shell>
  );
}

/** The page the verification link opens. */
export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "failed">(token ? "working" : "failed");

  useEffect(() => {
    if (!token) return;
    verifyEmail(token).then(() => setState("ok")).catch(() => setState("failed"));
  }, [token]);

  return (
    <Shell title="Confirm your email address">
      {state === "working" && <p className="text-sm text-muted-foreground">Checking your link...</p>}
      {state === "ok" && <Notice tone="good">Thank you, your email address is confirmed.</Notice>}
      {state === "failed" && <Notice tone="warn">This link is not valid any more. Log in and ask for a new confirmation email.</Notice>}
    </Shell>
  );
}
