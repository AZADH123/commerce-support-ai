import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setAccessToken, setOnUnauthorized } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client request wrapper", () => {
  beforeEach(() => {
    setAccessToken(null);
    setOnUnauthorized(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the bearer token and returns parsed JSON", async () => {
    setAccessToken("token-abc");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    // Use the internal request via a public endpoint that hits the wrapper.
    const { api } = await import("./client");
    const result = await api.getMe();

    expect(result).toEqual({ ok: true });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-abc");
  });

  it("raises ApiError with the server detail on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(422, { detail: "A reason is required" })),
    );
    const { api } = await import("./client");
    await expect(api.reject(1, {})).rejects.toMatchObject({
      status: 422,
      message: "A reason is required",
    });
  });

  it("calls the unauthorized handler and raises on 401", async () => {
    const handler = vi.fn();
    setOnUnauthorized(handler);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { detail: "nope" })));
    const { api } = await import("./client");
    await expect(api.getMe()).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalled();
  });
});
