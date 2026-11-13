import { Navigate } from "react-router-dom";
import { useAuth } from "../../auth/useAuth";

export function SignInPage() {
  const { signIn, error, user } = useAuth();

  if (user) {
    return <Navigate to="/chat" replace />;
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Commerce Support</h1>
        <p className="auth-subtitle">Sign in to chat about your orders or review refund requests.</p>
        <button type="button" className="button button-primary" onClick={() => void signIn()}>
          Sign in with Keycloak
        </button>
        {error && (
          <div className="state state-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
