/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Public configuration only — never secrets or tokens.
  readonly VITE_OIDC_REDIRECT_URI?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
