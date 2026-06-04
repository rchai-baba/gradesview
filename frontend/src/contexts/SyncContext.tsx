import { createContext, useContext, useRef, useState, useCallback, type ReactNode } from "react";
import { loginAndFetchGrades, saveGrades, getSessionCredentials, backgroundSyncAllDetails } from "@/services/api";

interface SyncContextValue {
  syncing: boolean;
  triggerSync: () => void;
  triggerBackgroundDetailSync: () => void;
  onSyncComplete: (cb: () => void) => () => void;
}

const SyncContext = createContext<SyncContextValue | null>(null);

export function SyncProvider({ children }: { children: ReactNode }) {
  const [syncing, setSyncing] = useState(false);
  const syncingRef = useRef(false);
  const detailSyncingRef = useRef(false);
  const listenersRef = useRef<Set<() => void>>(new Set());

  const notify = useCallback(() => {
    for (const cb of listenersRef.current) cb();
  }, []);

  const onSyncComplete = useCallback((cb: () => void) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  }, []);

  // Background detail sync: fetch assignments for all unloaded class×period combos.
  // Does not set syncing=true (silent background work).
  const triggerBackgroundDetailSync = useCallback(() => {
    if (detailSyncingRef.current) return;
    const creds = getSessionCredentials();
    if (!creds) return;
    detailSyncingRef.current = true;
    (async () => {
      try {
        await backgroundSyncAllDetails(creds.username, creds.password, notify);
      } catch (e) {
        console.error("Background detail sync failed:", e);
      } finally {
        detailSyncingRef.current = false;
      }
    })();
  }, [notify]);

  // Full sync: re-login (refresh grade cards), then background-fetch all details.
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
        notify();
        // After cards land, kick off detail sync (silent)
        detailSyncingRef.current = false;
        triggerBackgroundDetailSync();
      } catch (e) {
        console.error("Sync failed:", e);
      } finally {
        syncingRef.current = false;
        setSyncing(false);
      }
    })();
  }, [notify, triggerBackgroundDetailSync]);

  return (
    <SyncContext.Provider value={{ syncing, triggerSync, triggerBackgroundDetailSync, onSyncComplete }}>
      {children}
    </SyncContext.Provider>
  );
}

export function useSyncContext() {
  const ctx = useContext(SyncContext);
  if (!ctx) throw new Error("useSyncContext must be used within SyncProvider");
  return ctx;
}
