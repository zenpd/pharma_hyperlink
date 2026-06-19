/**
 * ActiveRun context
 *
 * Holds the "active" pipeline run that every screen reads from. Until the user
 * makes an explicit choice we auto-select the newest completed run — so the
 * moment a pipeline run finishes, the dashboard reflects it. `activeRunId === ""`
 * means "show the seeded demo dossier" (the live `/api/dossiers/demo/...`
 * endpoints), which the user can always switch back to from the Run Selector.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { RunSummary } from "../types";

interface ActiveRunValue {
  runs: RunSummary[];                 // completed runs, newest first
  activeRunId: string;                // "" => demo seed data
  setActiveRunId: (id: string) => void;
  refresh: () => void;
  loading: boolean;
}

const ActiveRunContext = createContext<ActiveRunValue>({
  runs: [],
  activeRunId: "",
  setActiveRunId: () => {},
  refresh: () => {},
  loading: false,
});

export function useActiveRun(): ActiveRunValue {
  return useContext(ActiveRunContext);
}

export function ActiveRunProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeRunId, setActiveRunIdRaw] = useState("");
  const [userChose, setUserChose] = useState(false);
  const [loading, setLoading] = useState(false);

  // Explicit user selection (a run OR "" for demo) freezes auto-selection.
  const setActiveRunId = useCallback((id: string) => {
    setUserChose(true);
    setActiveRunIdRaw(id);
  }, []);

  const refresh = useCallback(() => {
    setLoading(true);
    api.pipeline
      .listRuns()
      .then(({ runs: all }) => {
        // Completed runs only, newest first (list_runs returns oldest→newest).
        const done = (all ?? []).filter((r) => r.status === "done").reverse();
        setRuns(done);
        // Auto-follow the newest completed run until the user chooses manually.
        if (!userChose && done.length > 0) {
          setActiveRunIdRaw(done[0].run_id);
        }
      })
      .catch(() => {
        /* best-effort — demo fallback stays in place */
      })
      .finally(() => setLoading(false));
  }, [userChose]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <ActiveRunContext.Provider value={{ runs, activeRunId, setActiveRunId, refresh, loading }}>
      {children}
    </ActiveRunContext.Provider>
  );
}
