import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { useAuth } from "./AuthContext";

/** Which of the user's analyses the pages are showing. Kept per tab (sessionStorage) and cleared on logout. */
const KEY = "finsight.uploadId";

function read(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

interface AppContextType {
  uploadId: string | null;
  setUploadId: (id: string | null) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [uploadId, setUploadIdState] = useState<string | null>(read);

  const setUploadId = (id: string | null) => {
    setUploadIdState(id);
    try {
      if (id) sessionStorage.setItem(KEY, id);
      else sessionStorage.removeItem(KEY);
    } catch {
      /* storage unavailable: the selection just will not survive a refresh */
    }
  };

  useEffect(() => {
    // Uploads belong to one user, so never carry a selection across logins.
    if (status === "anonymous") {
      setUploadIdState(null);
      try {
        sessionStorage.removeItem(KEY);
      } catch {
        /* nothing to clear */
      }
    }
  }, [status]);

  return <AppContext.Provider value={{ uploadId, setUploadId }}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextType {
  const context = useContext(AppContext);
  if (context === undefined) throw new Error("useAppContext must be used within an AppProvider");
  return context;
}
