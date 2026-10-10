import { FormEvent, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { ApiError } from "../../api";
import { useAuth } from "../../context/AuthContext";
import { CredentialErrors, serverFieldErrors, validateCredentials } from "../../lib/validation";
import { AuthForm } from "../AuthForm";
import { ErrorNotice, Notice, Spinner } from "../common";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { status, notice, login, register, clearNotice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<CredentialErrors>({});
  const [formError, setFormError] = useState<unknown>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const isLogin = mode === "login";
  const destination = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "loading") return <div className="flex min-h-screen items-center justify-center bg-background"><Spinner label="Checking your session..." /></div>;
  if (status === "authenticated") return <Navigate to={destination} replace />;

  function recheck(field: "email" | "password") {
    // after the person has left a field, show what is wrong with it straight away
    const found = validateCredentials(mode, email, password);
    setFieldErrors((current) => ({ ...current, [field]: found[field] }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const found = validateCredentials(mode, email, password);
    setFieldErrors(found);
    if (found.email) return void emailRef.current?.focus();
    if (found.password) return void passwordRef.current?.focus();

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
          mode={mode} email={email} password={password} errors={fieldErrors} busy={busy} emailRef={emailRef} passwordRef={passwordRef}
          onEmail={setEmail} onPassword={setPassword} onBlurField={recheck} onSubmit={submit}
        >
          {notice && <Notice tone="warn">{notice}</Notice>}
          {formError !== null && <ErrorNotice error={formError} />}
        </AuthForm>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          {isLogin ? "New here?" : "Already have an account?"}{" "}
          <Link to={isLogin ? "/register" : "/login"} onClick={clearNotice} className="text-primary underline-offset-4 hover:underline">
            {isLogin ? "Create an account" : "Log in"}
          </Link>
        </p>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          This is a demo project, so please use practice data. Everything you upload stays until you delete that analysis.
        </p>
      </div>
    </div>
  );
}
