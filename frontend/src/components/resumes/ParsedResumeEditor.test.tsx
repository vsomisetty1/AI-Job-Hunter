import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockFetch, parsedResume } from "@/test/factories";

import { normalizeParsed, ParsedResumeEditor } from "./ParsedResumeEditor";
import { ParsedResumeView } from "./ParsedResumeView";

afterEach(() => vi.unstubAllGlobals());

describe("normalizeParsed", () => {
  it("trims, nulls empty strings and drops empty entries", () => {
    const out = normalizeParsed(
      parsedResume({
        summary: "  ",
        experience: [
          { title: " Eng ", company: "", location: null, start_date: "", end_date: null,
            is_current: false, bullets: ["a", " ", "b "], skills: [] },
          { title: "", company: "", location: null, start_date: null, end_date: null,
            is_current: false, bullets: [], skills: [] },
        ],
      }),
    );
    expect(out.summary).toBeNull();
    expect(out.experience).toHaveLength(1);
    expect(out.experience[0]).toMatchObject({ title: "Eng", company: null, bullets: ["a", "b"] });
  });
});

describe("ParsedResumeEditor", () => {
  it("saves edits as a new version", async () => {
    const fetch = mockFetch(json({ id: "v3" }, 201));
    const onSaved = vi.fn();
    render(<ParsedResumeEditor resumeId="r1" initial={parsedResume()} onSaved={onSaved} onCancel={() => {}} />);

    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Jordan A. Rivera");
    await userEvent.click(screen.getByRole("button", { name: "Add experience" }));
    await userEvent.type(screen.getByLabelText("Title (Experience 2)"), "Intern");
    await userEvent.type(screen.getByLabelText("What changed? (optional)"), "Fixed name");
    await userEvent.click(screen.getByRole("button", { name: "Save as new version" }));

    expect(onSaved).toHaveBeenCalled();
    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/resumes\/r1\/parsed$/);
    expect(init?.method).toBe("PUT");
    const body = JSON.parse(init!.body as string);
    expect(body.change_summary).toBe("Fixed name");
    expect(body.data.contact.name).toBe("Jordan A. Rivera");
    expect(body.data.experience.map((e: { title: string }) => e.title)).toEqual(["Senior Engineer", "Intern"]);
    expect(body.data.skills).toEqual(["Python", "Go"]);
  });
});

describe("ParsedResumeView", () => {
  it("never renders non-http links", () => {
    render(
      <ParsedResumeView
        data={parsedResume({
          contact: { ...parsedResume().contact, linkedin: "javascript:alert(1)", portfolio: "https://me.dev" },
        })}
      />,
    );
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["https://me.dev/"]);
  });
});
