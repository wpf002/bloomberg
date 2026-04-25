import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";

// Polls /api/auth/me on mount + after a manual refresh to determine login
// state. Also reads /api/auth/status so the UI can hide the GitHub button
// when OAuth env vars aren't configured (instead of redirecting into a 503).
export default function useAuth() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [oauthConfigured, setOauthConfigured] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [me, status] = await Promise.all([
        api.authMe().catch(() => null),
        api.authStatus().catch(() => ({ github_configured: false })),
      ]);
      setUser(me ?? null);
      setOauthConfigured(Boolean(status?.github_configured));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(() => {
    if (!oauthConfigured) return;
    window.location.assign(api.authLoginUrl());
  }, [oauthConfigured]);

  const logout = useCallback(async () => {
    try {
      await api.authLogout();
    } catch (err) {
      // Server is the source of truth, but if it's unreachable, clear locally.
    }
    setUser(null);
  }, []);

  return { user, loading, oauthConfigured, login, logout, refresh };
}
