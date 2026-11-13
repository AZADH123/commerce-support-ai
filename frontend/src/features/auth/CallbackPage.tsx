import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../auth/useAuth";
import { Loading, ErrorState } from "../../components/states";

export function CallbackPage() {
  const [searchParams] = useSearchParams();
  const { handleCallback, error } = useAuth();

  const code = searchParams.get("code");
  const state = searchParams.get("state");

  useEffect(() => {
    if (code && state) {
      void handleCallback(code, state);
    }
    // Run once per mounted callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) {
    return <ErrorState message={error} />;
  }
  if (!code || !state) {
    return <ErrorState message="Missing OIDC callback parameters." />;
  }
  return <Loading label="Completing sign in…" />;
}
