import { describe, expect, it } from "vitest";

import {
  csvToList,
  formatBytes,
  formatDuration,
  formatRange,
  formatYearMonth,
  linesToList,
  safeUrl,
} from "./format";

describe("format helpers", () => {
  it("formats sizes and dates", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatYearMonth("2021-03")).toBe("Mar 2021");
    expect(formatYearMonth("2019")).toBe("2019");
    expect(formatRange("2021-01", null, true)).toBe("Jan 2021 – Present");
    expect(formatRange(null, "2020", false)).toBe("2020");
    expect(formatDuration(27)).toBe("2 yrs 3 mo");
    expect(formatDuration(null)).toBe("");
  });

  it("converts list inputs", () => {
    expect(csvToList(" Python, go , Python,, Go ")).toEqual(["Python", "go"]);
    expect(linesToList("a\n\n b \n")).toEqual(["a", "b"]);
  });

  it("only allows http(s) links", () => {
    expect(safeUrl("https://example.com/x")).toBe("https://example.com/x");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("data:text/html,hi")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
    expect(safeUrl(null)).toBeNull();
  });
});

describe("formatSalary", () => {
  it("formats ranges, open ends and unknown currencies", async () => {
    const { formatSalary } = await import("./format");
    expect(formatSalary(120000, 150000, "USD")).toBe("$120k – $150k");
    expect(formatSalary(90000, null, "EUR")).toBe("€90k+");
    expect(formatSalary(null, 80000, "SEK")).toBe("up to 80k SEK");
    expect(formatSalary(null, null, "USD")).toBe("");
  });
});

describe("formatRelative", () => {
  it("uses short relative units", async () => {
    const { formatRelative } = await import("./format");
    const now = Date.parse("2026-11-27T12:00:00Z");
    expect(formatRelative("2026-11-27T11:59:30Z", now)).toBe("just now");
    expect(formatRelative("2026-11-27T11:00:00Z", now)).toBe("1 h ago");
    expect(formatRelative("2026-11-24T12:00:00Z", now)).toBe("3 d ago");
    expect(formatRelative(null, now)).toBe("");
  });
});
