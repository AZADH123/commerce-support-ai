import { createContext, useContext } from "react";
import type { Me } from "../api/types";

export interface AuthContextValue {
  user: Me | null;
  loading: boolean;
  error: string | null;
  signIn: () => Promise<void>;
  handleCallback: (code: string, state: string) => Promise<void>;
  signOut: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider.");
  return context;
}
