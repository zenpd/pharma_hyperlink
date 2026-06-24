/**
 * Auth context — PLAN SEVEN.
 *
 * Single source of truth for the security gate + the logged-in user:
 *
 *   - On mount: GET /api/security/mode (public). If the gate is OFF the app
 *     renders exactly as before — no login, full access, `user` is the open
 *     system principal returned by /api/me.
 *   - If the gate is ON: GET /api/me probes the session cookie. A 401 means
 *     "nobody is logged in" → `authRequired` flips true and the App shell
 *     swaps to the Login screen.
 *   - Any API call anywhere that 401s broadcasts UNAUTHORIZED_EVENT (api.ts);
 *     we listen and re-probe, so an expired session lands on Login.
 *
 * Sessions are httpOnly cookies managed by the backend's SuperTokens
 * middleware — there is nothing to store client-side.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, UNAUTHORIZED_EVENT } from "../api";
import type { Me, SecurityMode } from "../types";

interface AuthState {
  /** Initial probe still running — render nothing yet to avoid a login flash. */
  loading: boolean;
  /** Security gate status (Feature C). */
  mode: SecurityMode | null;
  /** The resolved caller; null while the gate is on and nobody is signed in. */
  user: Me | null;
  /** True when the gate is on and there is no session → show Login. */
  authRequired: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Flip the security gate (admin-only while active; server enforces). */
  setSecurityEnabled: (enabled: boolean) => Promise<void>;
  /** Re-probe gate + session (e.g. after an external change). */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<SecurityMode | null>(null);
  const [user, setUser] = useState<Me | null>(null);

  const probe = useCallback(async () => {
    let m: SecurityMode | null = null;
    try {
      m = await api.security.mode();
    } catch {
      // Backend unreachable / endpoint missing → behave as if the gate is off
      // so the rest of the app can surface its own connection errors.
      m = null;
    }
    setMode(m);
    try {
      setUser(await api.auth.me());
    } catch {
      setUser(null); // 401 (login needed) or backend down
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    probe();
  }, [probe]);

  // An expired/revoked session anywhere in the app re-triggers the probe.
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      api.security.mode().then(setMode).catch(() => {});
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setUser(await api.auth.login(email, password));
  }, []);

  const signup = useCallback(async (email: string, password: string) => {
    setUser(await api.auth.signup(email, password));
  }, []);

  const logout = useCallback(async () => {
    await api.auth.logout();
    setUser(null);
  }, []);

  const setSecurityEnabled = useCallback(async (enabled: boolean) => {
    setMode(await api.security.setMode(enabled));
    // Turning the gate on invalidates the open system principal; re-probe so
    // the login screen appears immediately when there is no real session.
    try {
      setUser(await api.auth.me());
    } catch {
      setUser(null);
    }
  }, []);

  const enabled = !!mode?.enabled;
  const value: AuthState = {
    loading,
    mode,
    user,
    authRequired: enabled && !user,
    login,
    signup,
    logout,
    setSecurityEnabled,
    refresh: probe,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
