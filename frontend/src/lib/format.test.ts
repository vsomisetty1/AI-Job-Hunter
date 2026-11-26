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
