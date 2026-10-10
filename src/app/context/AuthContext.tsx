import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import * as api from "../api";
import { useIdleLogout } from "../hooks/useIdleLogout";
import { IDLE_NOTICE } from "../lib/idle";
import type { User } from "../types";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthValue {
  user: User | null;
  status: AuthStatus;
  /** A message to show on the login page, for example "Your session expired". */
  notice: string | null;
  /** True when the browser did not keep the login cookie, so a page reload will log the person out. */
  cookieWarning: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: (reason?: "idle") => void;
  clearNotice: () => void;
}

const AuthContext = createContext<AuthValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // After a page load there is no access token in memory, so we always ask the server whether the refresh cookie
  // still represents a valid session.
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [notice, setNotice] = useState<string | null>(null);
  const [cookieWarning, setCookieWarning] = useState(false);

  useEffect(() => {
    // Any request that comes back 401 (expired or invalid token) ends the session in one place.
    api.setUnauthorizedHandler((reason) => {
      setUser(null);
      setStatus("anonymous");
      setNotice(reason === "expired" ? "Your session expired. Please log in again." : "Please log in to continue.");
    });
    let cancelled = false;
    void (async () => {
      const outcome = await api.refreshSession(); // silent login from the HttpOnly cookie
      if (cancelled) return;
      if (outcome === "ok") {
        try {
          const me = await api.getMe();
          if (cancelled) return;
          setUser(me);
          setStatus("authenticated");
          return;
        } catch {
          /* fall through to anonymous */
        }
      }
      setStatus("anonymous");
      if (outcome === "unreachable") setNotice("Cannot reach the server. Check your connection and try again.");
    })();
    return () => {
      cancelled = true;
      api.setUnauthorizedHandler(null);
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const token = await api.login(email, password);
    api.tokenStore.set(token.access_token);
    try {
      setUser(await api.getMe());
    } catch (error) {
      api.tokenStore.clear();
      throw error;
    }
    setStatus("authenticated");
    setNotice(null);
    void api.verifySessionCookie().then((keptCookie) => setCookieWarning(!keptCookie));
  }, []);

  const endSession = useCallback((reason?: "idle") => {
    void api.logout().catch(() => undefined); // revoke the session on the server (best effort)
    api.tokenStore.clear();
    setUser(null);
    setStatus("anonymous");
    setNotice(reason === "idle" ? IDLE_NOTICE : null);
    setCookieWarning(false);
  }, []);

  // No activity for 15 minutes: end the session on the server too, so the refresh cookie stops working as well.
  const onIdle = useCallback(() => endSession("idle"), [endSession]);
  useIdleLogout(status === "authenticated", onIdle);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      status,
      notice,
      cookieWarning,
      login: signIn,
      register: async (email, password) => {
        await api.register(email, password);
        await signIn(email, password);
      },
      logout: endSession,
      clearNotice: () => setNotice(null),
    }),
    [user, status, notice, cookieWarning, signIn, endSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
}
