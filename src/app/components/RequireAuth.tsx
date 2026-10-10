import { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "../context/AuthContext";
import { Spinner } from "./common";

/** Sends visitors who are not logged in to the login page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <div className="flex h-screen items-center justify-center bg-background"><Spinner label="Checking your session..." /></div>;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}
