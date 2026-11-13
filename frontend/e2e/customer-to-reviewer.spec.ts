// Customer → reviewer refund flow with policy citations and execution timeline.
//
// Live end-to-end check (requires the full local stack):
//   1. docker compose up -d                 (PostgreSQL+pgvector, Redis, Mailpit, Keycloak)
//   2. alembic upgrade head
//   3. python -m src.backend.seed
//   4. python -m src.knowledge.ingest
//   5. uvicorn api:app --reload             (backend :8000)
//   6. python -m src.tasks.dispatch --loop  (outbox dispatcher)
//   7. taskiq worker src.tasks.broker:broker src.tasks.refund_tasks (worker)
//   8. cd frontend && npm run dev           (Vite :5173)
//   9. npx playwright install chromium
//  10. npx playwright test
//
// Demo users (password "password"):
//   alice@example.com / bob@example.com (customers), reviewer@example.com (reviewer)

import { expect, test, type Page } from "@playwright/test";

async function signIn(page: Page, username: string): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: /sign in with keycloak/i }).click();

  // Keycloak login form.
  await page.waitForSelector("#username");
  await page.fill("#username", username);
  await page.fill("#password", "password");
  await page.click("#kc-login");
  await page.waitForURL(/\/chat/);
}

async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: /sign out/i }).click();
  await page.waitForURL(/\/login/);
}

test("customer cites policy, requests a refund, and reviewer approves it", async ({ page }) => {
  await signIn(page, "alice");

  // FAQ answer cites a versioned store policy.
  await page.fill("#chat-input", "How long does shipping take?");
  await page.getByRole("button", { name: /send/i }).click();
  await expect(page.locator(".citation").first()).toBeVisible();

  // Customer requests a refund on their delivered order 1001.
  await page.fill("#chat-input", "I want a refund for order 1001, it arrived broken.");
  await page.getByRole("button", { name: /send/i }).click();
  await page.getByRole("link", { name: /my cases/i }).click();
  await expect(page.locator(".case-card").first()).toBeVisible();
  await signOut(page);

  // Reviewer finds it in the queue and approves it.
  await signIn(page, "reviewer");
  await page.getByRole("link", { name: /review queue/i }).click();
  await page.locator(".case-card").first().click();
  await expect(page.getByText(/pending review/i)).toBeVisible();

  await page.fill("#decision-reason", "Approved after inspection.");
  await page.getByRole("button", { name: /approve/i }).click();
  await expect(page.getByText("Execution")).toBeVisible();
  await signOut(page);

  // Customer sees the refund advance through the timeline (polling is bounded).
  await signIn(page, "alice");
  await page.getByRole("link", { name: /my cases/i }).click();
  await page.locator(".case-card").first().click();
  await expect(page.locator(".case-banner-status")).toHaveText(/refunded/i, { timeout: 90_000 });
  await expect(page.locator(".timeline-step", { hasText: /refunded/i })).toBeVisible();
});
