import { createContext, useContext, useRef, useState, useCallback, type ReactNode } from "react";
import { loginAndFetchGrades, saveGrades, getSessionCredentials } from "@/services/api";

interface SyncContextValue {
  syncing: boolean;
  triggerSync: () => void;
  onSyncComplete: (cb: () => void) => () => void;
}

const SyncContext = createContext<SyncContextValue | null>(null);

export function SyncProvider({ children }: { children: ReactNode }) {
  const [syncing, setSyncing] = useState(false);
  const syncingRef = useRef(false);
  const listenersRef = useRef<Set<() => void>>(new Set());

  const onSyncComplete = useCallback((cb: () => void) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  }, []);

  const triggerSync = useCallback(() => {
    if (syncingRef.current) return;
    const creds = getSessionCredentials();
    if (!creds) return;
    syncingRef.current = true;
    setSyncing(true);
    (async () => {
      try {
        const res = await loginAndFetchGrades(creds.username, creds.password);
        saveGrades(res);
        for (const cb of listenersRef.current) cb();
      } catch (e) {
        console.error("Background sync failed:", e);
      } finally {
        syncingRef.current = false;
        setSyncing(false);
      }
    })();
  }, []);

  return (
    <SyncContext.Provider value={{ syncing, triggerSync, onSyncComplete }}>
      {children}
    </SyncContext.Provider>
  );
}

export function useSyncContext() {
  const ctx = useContext(SyncContext);
  if (!ctx) throw new Error("useSyncContext must be used within SyncProvider");
  return ctx;
}
