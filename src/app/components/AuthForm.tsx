import type { FormEvent, ReactNode, RefObject } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "./ui/button";
import type { CredentialErrors } from "../lib/validation";

interface AuthFormProps {
  mode: "login" | "register";
  email: string;
  password: string;
  errors: CredentialErrors;
  busy: boolean;
  emailRef?: RefObject<HTMLInputElement>;
  passwordRef?: RefObject<HTMLInputElement>;
  onEmail: (value: string) => void;
  onPassword: (value: string) => void;
  onBlurField: (field: "email" | "password") => void;
  onSubmit: (event: FormEvent) => void;
  children?: ReactNode; // notices and errors that belong above the fields
}

const base = "w-full rounded-md border bg-input px-3 py-2 text-sm text-foreground outline-none focus:ring-2";
const ok = "border-border focus:border-primary focus:ring-primary/30";
const bad = "border-destructive focus:border-destructive focus:ring-destructive/30";

/** The login/register form. Messages appear inline in the app's own colours; nothing floats over the fields. */
export function AuthForm({ mode, email, password, errors, busy, emailRef, passwordRef, onEmail, onPassword, onBlurField, onSubmit, children }: AuthFormProps) {
  const isLogin = mode === "login";
  return (
    // noValidate: the browser's own pop-up bubbles are replaced by the messages below
    <form onSubmit={onSubmit} noValidate className="space-y-4 rounded-lg border border-border bg-card p-6">
      <h2 className="font-sans text-xl text-foreground">{isLogin ? "Log in" : "Create an account"}</h2>
      {children}
      <div>
        <label htmlFor="email" className="mb-1 block text-sm text-muted-foreground">Email</label>
        <input
          id="email" ref={emailRef} type="email" autoComplete="email" value={email} aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? "email-error" : undefined} onChange={(e) => onEmail(e.target.value)} onBlur={() => onBlurField("email")}
          className={`${base} ${errors.email ? bad : ok}`}
        />
        {errors.email && <p id="email-error" role="alert" className="mt-1 text-sm text-destructive">{errors.email}</p>}
      </div>
      <div>
        <label htmlFor="password" className="mb-1 block text-sm text-muted-foreground">Password</label>
        <input
          id="password" ref={passwordRef} type="password" autoComplete={isLogin ? "current-password" : "new-password"} value={password}
          aria-invalid={errors.password ? true : undefined} aria-describedby={errors.password ? "password-error password-hint" : "password-hint"}
          onChange={(e) => onPassword(e.target.value)} onBlur={() => onBlurField("password")} className={`${base} ${errors.password ? bad : ok}`}
        />
        {errors.password && <p id="password-error" role="alert" className="mt-1 text-sm text-destructive">{errors.password}</p>}
        {!isLogin && <p id="password-hint" className="mt-1 text-xs text-muted-foreground">At least 8 characters.</p>}
      </div>
      <Button type="submit" disabled={busy} className="w-full">
        {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {isLogin ? "Log in" : "Create account"}
      </Button>
    </form>
  );
}
