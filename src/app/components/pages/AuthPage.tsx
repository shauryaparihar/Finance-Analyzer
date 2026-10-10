import { FormEvent, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router";
import { ApiError, GOOGLE_LOGIN_URL, getProviders } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useAuth } from "../../context/AuthContext";
import { CredentialErrors, serverFieldErrors, validateCredentials } from "../../lib/validation";
import { AuthForm } from "../AuthForm";
import { ErrorNotice, Notice, Spinner } from "../common";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { status, notice, login, loginAsDemo, register, clearNotice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<CredentialErrors>({});
  const [formError, setFormError] = useState<unknown>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const isLogin = mode === "login";
  const providers = useResource(() => getProviders().catch(() => ({ google: false, demo: false })), []).data;
  const [params] = useSearchParams();
  const googleFailed = params.get("google") === "failed";
  const destination = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "loading") return <div className="flex min-h-screen items-center justify-center bg-background"><Spinner label="Checking your session..." /></div>;
  if (status === "authenticated") return <Navigate to={destination} replace />;

  function recheck(field: "email" | "password" | "confirm") {
    // after the person has left a field, show what is wrong with it straight away
    const found = validateCredentials(mode, email, password, isLogin ? undefined : confirm);
    setFieldErrors((current) => ({ ...current, [field]: found[field] }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const found = validateCredentials(mode, email, password, isLogin ? undefined : confirm);
    setFieldErrors(found);
    if (found.email) return void emailRef.current?.focus();
    if (found.password) return void passwordRef.current?.focus();
    if (found.confirm) return void confirmRef.current?.focus();

    setBusy(true);
    try {
      await (isLogin ? login(email.trim(), password) : register(email.trim(), password));
      navigate(destination, { replace: true });
    } catch (e) {
      const fromServer = e instanceof ApiError ? serverFieldErrors(e.problems) : {};
      if (fromServer.email || fromServer.password) setFieldErrors(fromServer); // show it under the field it is about
      else setFormError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-sans text-3xl tracking-tight text-primary">FinSight</h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">BUDGET RISK &amp; TRANSACTION REVIEW</p>
        </div>
        <AuthForm
          mode={mode} email={email} password={password} confirm={confirm} errors={fieldErrors} busy={busy}
          emailRef={emailRef} passwordRef={passwordRef} confirmRef={confirmRef}
          onEmail={setEmail} onPassword={setPassword} onConfirm={setConfirm} onBlurField={recheck} onSubmit={submit}
        >
          {notice && <Notice tone="warn">{notice}</Notice>}
          {googleFailed && <Notice tone="warn">Google sign-in did not complete. Please try again, or use your email and password.</Notice>}
          {formError !== null && <ErrorNotice error={formError} />}
        </AuthForm>
        {providers?.google && (
          <a
            href={GOOGLE_LOGIN_URL}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm text-foreground transition-colors hover:bg-secondary"
          >
            Continue with Google
          </a>
        )}
        {isLogin && providers?.demo && (
          <div className="mt-4 text-center">
            <button
              type="button" disabled={busy} className="text-sm text-primary underline-offset-4 hover:underline disabled:opacity-60"
              onClick={async () => {
                setFormError(null);
                setBusy(true);
                try {
                  await loginAsDemo();
                  navigate(destination, { replace: true });
                } catch (e) {
                  setFormError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Just looking? Try the read-only demo
            </button>
          </div>
        )}
        <p className="mt-4 text-center text-sm text-muted-foreground">
          {isLogin ? "New here?" : "Already have an account?"}{" "}
          <Link to={isLogin ? "/register" : "/login"} onClick={clearNotice} className="text-primary underline-offset-4 hover:underline">
            {isLogin ? "Create an account" : "Log in"}
          </Link>
        </p>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          Everything you upload stays until you delete that analysis.
        </p>
      </div>
    </div>
  );
}
