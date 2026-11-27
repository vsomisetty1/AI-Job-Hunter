import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockFetch, profile } from "@/test/factories";

import { diffProfile, ProfileEditor } from "./ProfileEditor";
import { ProfileView } from "./ProfileView";

afterEach(() => vi.unstubAllGlobals());

describe("diffProfile", () => {
  it("returns only changed fields", () => {
    const p = profile();
    expect(diffProfile(p, { full_name: p.full_name, skills: ["Python"] })).toEqual({});
    expect(diffProfile(p, { skills: ["Python", "Go"], headline: "New" })).toEqual({
      skills: ["Python", "Go"],
      headline: "New",
    });
  });
});

describe("ProfileEditor", () => {
  it("PATCHes only the edited fields", async () => {
    const updated = profile({ headline: "Platform engineer", overrides: ["headline"] });
    const fetch = mockFetch(json(updated));
    const onSaved = vi.fn();
    render(<ProfileEditor profile={profile()} onSaved={onSaved} onCancel={() => {}} />);
    const headline = screen.getByLabelText("Headline");
    await userEvent.clear(headline);
    await userEvent.type(headline, "Platform engineer");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({ headline: "Platform engineer" });
    expect(onSaved).toHaveBeenCalledWith(updated);
  });
});

describe("ProfileView", () => {
  it("shows inferred data and marks edited fields", () => {
    render(<ProfileView profile={profile({ overrides: ["inferred_roles"] })} />);
    expect(screen.getByText("Engineering Manager")).toBeInTheDocument();
    expect(screen.getByText("Backend Engineer")).toBeInTheDocument();
    expect(screen.getByText("edited")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();
  });
});
