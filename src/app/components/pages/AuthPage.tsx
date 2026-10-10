import { FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { Loader2 } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../ui/button";
import { ErrorNotice, Notice } from "../common";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { status, notice, login, register, clearNotice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const isLogin = mode === "login";
  const destination = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "authenticated") return <Navigate to={destination} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (isLogin ? login(email, password) : register(email, password));
      navigate(destination, { replace: true });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/30";

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-sans text-3xl tracking-tight text-primary">FinSight</h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">BUDGET RISK &amp; TRANSACTION REVIEW</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-border bg-card p-6" noValidate={false}>
          <h2 className="font-sans text-xl text-foreground">{isLogin ? "Log in" : "Create an account"}</h2>
          {notice && <Notice tone="warn">{notice}</Notice>}
          {error !== null && <ErrorNotice error={error} />}
          <div>
            <label htmlFor="email" className="mb-1 block text-sm text-muted-foreground">Email</label>
            <input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
          </div>
          <div>
            <label htmlFor="password" className="mb-1 block text-sm text-muted-foreground">Password</label>
            <input
              id="password" type="password" required minLength={isLogin ? 1 : 8} autoComplete={isLogin ? "current-password" : "new-password"}
              value={password} onChange={(e) => setPassword(e.target.value)} className={input}
            />
            {!isLogin && <p className="mt-1 text-xs text-muted-foreground">At least 8 characters.</p>}
          </div>
          <Button type="submit" disabled={busy} className="w-full">
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isLogin ? "Log in" : "Create account"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            {isLogin ? "New here?" : "Already have an account?"}{" "}
            <Link to={isLogin ? "/register" : "/login"} onClick={clearNotice} className="text-primary underline-offset-4 hover:underline">
              {isLogin ? "Create an account" : "Log in"}
            </Link>
          </p>
        </form>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          This is a demo project, so please use practice data. Everything you upload stays until you delete that analysis.
        </p>
      </div>
    </div>
  );
}
