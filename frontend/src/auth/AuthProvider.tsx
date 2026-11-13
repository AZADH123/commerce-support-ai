import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, setAccessToken, setOnUnauthorized } from "../api/client";
import type { Me } from "../api/types";
import { beginAuthorization, exchangeCode, validateState } from "./oidc";
import { AuthContext } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    // Clear user-specific query cache (conversations, cases, queue).
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setOnUnauthorized(() => {
      clearSession();
      navigate("/login", { replace: true });
    });
    return () => setOnUnauthorized(null);
  }, [clearSession, navigate]);

  const signIn = useCallback(async () => {
    setError(null);
    try {
      const config = await api.getAuthConfig();
      await beginAuthorization(config);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to start sign in.");
    }
  }, []);

  const handleCallback = useCallback(
    async (code: string, state: string) => {
      setLoading(true);
      setError(null);
      try {
        validateState(state);
        const config = await api.getAuthConfig();
        const tokens = await exchangeCode(config, code);
        setAccessToken(tokens.access_token);
        const me = await api.getMe();
        setUser(me);
        navigate("/chat", { replace: true });
      } catch (e) {
        setError(e instanceof Error ? e.message : "Sign in failed.");
        navigate("/login", { replace: true });
      } finally {
        setLoading(false);
      }
    },
    [navigate],
  );

  const signOut = useCallback(() => {
    clearSession();
    navigate("/login", { replace: true });
  }, [clearSession, navigate]);

  const value = useMemo(
    () => ({ user, loading, error, signIn, handleCallback, signOut }),
    [user, loading, error, signIn, handleCallback, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
