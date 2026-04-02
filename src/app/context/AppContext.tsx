import React, { createContext, useContext, useState, useEffect } from 'react';

interface AppContextType {
  uploadId: string | null;
  setUploadId: (id: string | null) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [uploadId, setUploadIdState] = useState<string | null>(localStorage.getItem('uploadId'));
  const [isLoading, setIsLoading] = useState(false);

  const setUploadId = (id: string | null) => {
    setUploadIdState(id);
    if (id) {
      localStorage.setItem('uploadId', id);
    } else {
      localStorage.removeItem('uploadId');
    }
  };

  return (
    <AppContext.Provider value={{ uploadId, setUploadId, isLoading, setIsLoading }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
}
