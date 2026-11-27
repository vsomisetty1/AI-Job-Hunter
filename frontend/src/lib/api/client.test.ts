import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockFetch } from "@/test/factories";

import { ApiError, apiFetch } from "./client";
import { checkResumeFile, resumesApi } from "./resumes";

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("returns JSON and sends JSON bodies", async () => {
    const fetch = mockFetch(json({ ok: true }));
    await expect(apiFetch("/x", { method: "POST", body: "{}" })).resolves.toEqual({ ok: true });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/x");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("turns the error envelope into ApiError", async () => {
    mockFetch(json({ error: { code: "invalid_file", message: "Bad PDF", details: { a: 1 } } }, 422));
    const err = (await apiFetch("/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.code, err.message, err.details]).toEqual([422, "invalid_file", "Bad PDF", { a: 1 }]);
  });

  it("handles non-JSON errors, network failures and 204", async () => {
    mockFetch(new Response("gateway", { status: 502 }));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 502, code: "http_error" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(apiFetch("/x")).rejects.toMatchObject({ code: "network_error" });
    mockFetch(new Response(null, { status: 204 }));
    await expect(apiFetch("/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("uploads as multipart without forcing a JSON content type", async () => {
    const fetch = mockFetch(json({ resume: {}, task_id: "t1" }, 201));
    const file = new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" });
    await resumesApi.upload(file, true);
    const init = fetch.mock.calls[0][1]!;
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("make_primary")).toBe("true");
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });
});

describe("checkResumeFile", () => {
  const file = (name: string, size: number, type = "") =>
    new File([new Uint8Array(size)], name, { type });

  it("accepts PDF and DOCX", () => {
    expect(checkResumeFile(file("a.pdf", 10, "application/pdf"))).toBeNull();
    expect(checkResumeFile(file("a.DOCX", 10))).toBeNull();
  });

  it("rejects other types, empty and large files", () => {
    expect(checkResumeFile(file("a.txt", 10, "text/plain"))).toMatch(/Only PDF and DOCX/);
    expect(checkResumeFile(file("a.pdf", 0))).toMatch(/empty/);
    expect(checkResumeFile(file("a.pdf", 2 * 1024 * 1024), 1)).toMatch(/larger than 1 MB/);
  });
});
