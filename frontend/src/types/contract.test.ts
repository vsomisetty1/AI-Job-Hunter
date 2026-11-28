// Runtime half of the API contract (the type half is ./contract.ts): every
// request the frontend's API modules can make must be an operation the backend
// serves (API_OPERATIONS, generated from the backend's OpenAPI spec).
//
// Every function of every `*Api` object in src/lib/api is called with
// placeholder arguments while fetch is mocked; the method and path of each
// request (or each URL a function returns, for downloads) are matched against
// the backend's paths, with {params} matching one path segment.
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_PREFIX } from "@/lib/api/client";

import { API_OPERATIONS } from "./api.gen";

type ApiObject = Record<string, unknown>;

const modules = import.meta.glob<Record<string, unknown>>(
  ["../lib/api/*.ts", "!../lib/api/*.test.ts", "!../lib/api/client.ts"],
  { eager: true },
);

const apis: [string, ApiObject][] = Object.entries(modules).flatMap(([file, mod]) =>
  Object.entries(mod)
    .filter(([name, value]) => name.endsWith("Api") && typeof value === "object" && value !== null)
    .map(([name, value]): [string, ApiObject] => [
      `${file.split("/").pop()}:${name}`,
      value as ApiObject,
    ]),
);

const operations = API_OPERATIONS.map((op) => {
  const [method, path] = op.split(" ");
  const pattern = path.replace(/\{[^}]+\}/g, "[^/]+");
  return { op, method, regex: new RegExp(`^${pattern}$`) };
});

/** "/api/v1/jobs/x?q=1" (absolute or not) -> "/jobs/x" */
function apiPath(url: string): string {
  const { pathname } = new URL(url, "http://localhost");
  expect(pathname.startsWith(API_PREFIX + "/")).toBe(true);
  return pathname.slice(API_PREFIX.length);
}

function matches(method: string, path: string): string | undefined {
  return operations.find((o) => o.method === method && o.regex.test(path))?.op;
}

/** Placeholder arguments: ids, numbers and flags that produce a valid path. */
const ARGS = ["id-1", "id-2", "id-3", "id-4"];

afterEach(() => vi.unstubAllGlobals());

describe("API contract: frontend requests exist in the backend", () => {
  it("finds the API modules", () => {
    expect(apis.length).toBeGreaterThanOrEqual(10);
  });

  for (const [name, api] of apis) {
    for (const [fn, impl] of Object.entries(api)) {
      if (typeof impl !== "function") continue;
      it(`${name}.${fn}`, async () => {
        const calls: { method: string; url: string }[] = [];
        vi.stubGlobal(
          "fetch",
          vi.fn(async (url: string, init: RequestInit = {}) => {
            calls.push({ method: (init.method ?? "GET").toUpperCase(), url: String(url) });
            return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
          }),
        );
        const result: unknown = await (impl as (...a: unknown[]) => unknown)(...ARGS);
        if (typeof result === "string" && result.includes(API_PREFIX)) {
          calls.push({ method: "GET", url: result }); // a download/screenshot URL
        }
        expect(calls.length, `${fn} made no request and returned no API URL`).toBeGreaterThan(0);
        for (const call of calls) {
          const path = apiPath(call.url);
          expect(
            matches(call.method, path),
            `${call.method} ${path} is not served by the backend (see API_OPERATIONS)`,
          ).toBeDefined();
        }
      });
    }
  }
});

describe("API contract: the matcher itself", () => {
  it("rejects paths and methods the backend does not serve", () => {
    expect(matches("GET", "/jobs/abc")).toBe("GET /jobs/{job_id}");
    expect(matches("DELETE", "/jobs/abc")).toBeUndefined();
    expect(matches("GET", "/jobs/abc/nope")).toBeUndefined();
    expect(matches("GET", "/no-such-thing")).toBeUndefined();
  });
});
