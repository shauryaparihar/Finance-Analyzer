import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import * as api from "../api";
import type { User } from "../types";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthValue {
  user: User | null;
  status: AuthStatus;
  /** A message to show on the login page, for example "Your session expired". */
  notice: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  clearNotice: () => void;
}

const AuthContext = createContext<AuthValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>(() => (api.tokenStore.get() ? "loading" : "anonymous"));
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    // Any request that comes back 401 (expired or invalid token) ends the session in one place.
    api.setUnauthorizedHandler((reason) => {
      setUser(null);
      setStatus("anonymous");
      setNotice(reason === "expired" ? "Your session expired. Please log in again." : "Please log in to continue.");
    });
    if (api.tokenStore.get()) {
      // After a page refresh the token is still in this tab's sessionStorage: confirm it is still valid.
      api
        .getMe()
        .then((me) => {
          setUser(me);
          setStatus("authenticated");
        })
        .catch(() => setStatus("anonymous")); // a 401 has already set the notice
    }
    return () => api.setUnauthorizedHandler(null);
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
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      status,
      notice,
      login: signIn,
      register: async (email, password) => {
        await api.register(email, password);
        await signIn(email, password);
      },
      logout: () => {
        api.tokenStore.clear();
        setUser(null);
        setStatus("anonymous");
        setNotice(null);
      },
      clearNotice: () => setNotice(null),
    }),
    [user, status, notice, signIn],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider");
  return context;
}
