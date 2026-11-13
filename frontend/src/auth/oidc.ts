// Browser-side Authorization Code + PKCE against the Keycloak realm.
//
// Only the code_verifier and state are kept in sessionStorage (they must survive
// the redirect to Keycloak); the access token itself lives only in memory in
// ./api/client.ts and is never written to any browser storage or URL.

import type { OidcConfig } from "../api/types";

const STORAGE_KEY = "oidc-pkce";

interface PkceState {
  verifier: string;
  state: string;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(length = 64): string {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

export async function createPkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = randomString(64);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const challenge = base64UrlEncode(new Uint8Array(digest));
  return { verifier, challenge };
}

export function redirectUri(): string {
  const fromEnv = import.meta.env.VITE_OIDC_REDIRECT_URI;
  if (fromEnv) return fromEnv;
  return `${window.location.origin}/callback`;
}

export async function beginAuthorization(config: OidcConfig): Promise<void> {
  const { verifier, challenge } = await createPkcePair();
  const state = randomString(32);
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ verifier, state } satisfies PkceState));

  const params = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id,
    redirect_uri: redirectUri(),
    scope: config.scope,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  window.location.assign(`${config.authorize_endpoint}?${params.toString()}`);
}

export interface TokenSet {
  access_token: string;
  id_token?: string;
  expires_in?: number;
}

function readAndClearPkce(): PkceState {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  sessionStorage.removeItem(STORAGE_KEY);
  if (!raw) throw new Error("Missing PKCE state; please sign in again.");
  return JSON.parse(raw) as PkceState;
}

export function validateState(expectedState: string): void {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) throw new Error("Missing PKCE state; please sign in again.");
  const { state } = JSON.parse(raw) as PkceState;
  if (state !== expectedState) {
    sessionStorage.removeItem(STORAGE_KEY);
    throw new Error("OIDC state mismatch; possible CSRF attempt.");
  }
}

export async function exchangeCode(config: OidcConfig, code: string): Promise<TokenSet> {
  const { verifier } = readAndClearPkce();
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.client_id,
    code,
    redirect_uri: redirectUri(),
    code_verifier: verifier,
  });
  const response = await fetch(config.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) {
    throw new Error("Token exchange failed; please sign in again.");
  }
  return (await response.json()) as TokenSet;
}
