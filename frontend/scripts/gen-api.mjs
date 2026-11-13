// Regenerate src/api/schema.d.ts from the backend OpenAPI document.
//
// Usage (from frontend/):
//   npm run gen:api            # reads ./openapi.json
//   OPENAPI_URL=http://localhost:8000/openapi.json npm run gen:api
//
// openapi.json is produced by: python scripts/dump_openapi.py (repo root),
// or by any running `uvicorn api:app` at /openapi.json.
import { execSync } from "node:child_process";

const source = process.env.OPENAPI_URL || "./openapi.json";
console.log(`Generating src/api/schema.d.ts from ${source} ...`);
execSync(`npx openapi-typescript ${source} -o src/api/schema.d.ts`, {
  stdio: "inherit",
});
