import { vi } from "vitest";

import type { CandidateProfile, ParsedResume } from "@/types";

export function parsedResume(overrides: Partial<ParsedResume> = {}): ParsedResume {
  return {
    contact: {
      name: "Jordan Rivera",
      email: "jordan@example.com",
      phone: null,
      location: "San Francisco, CA",
      linkedin: "https://www.linkedin.com/in/jordan",
      github: null,
      portfolio: null,
      other_links: [],
    },
    summary: "Backend engineer.",
    experience: [
      {
        title: "Senior Engineer",
        company: "Acme Corp",
        location: null,
        start_date: "2021-01",
        end_date: null,
        is_current: true,
        bullets: ["Led migration"],
        skills: [],
      },
    ],
    education: [],
    skills: ["Python", "Go"],
    skill_groups: [],
    certifications: [],
    projects: [],
    publications: [],
    awards: [],
    languages: [],
    other_sections: [],
    meta: {
      method: "deterministic",
      parser_version: "1.0",
      confidence: 0.9,
      section_confidence: [],
      llm_sections: [],
      warnings: [],
    },
    ...overrides,
  };
}

export function profile(overrides: Partial<CandidateProfile> = {}): CandidateProfile {
  return {
    id: "p1",
    full_name: "Jordan Rivera",
    email: "jordan@example.com",
    phone: null,
    location: null,
    linkedin_url: "https://www.linkedin.com/in/jordan",
    portfolio_url: null,
    headline: "Backend engineer",
    summary: null,
    seniority: "senior",
    experience_level: "senior",
    years_of_experience: 7.5,
    skills: ["Python"],
    skill_groups: [],
    industries: ["Fintech"],
    inferred_roles: ["Backend Engineer"],
    transferable_roles: [{ title: "Engineering Manager", rationale: "Mentored engineers." }],
    career_history: [],
    education: [],
    education_summary: null,
    certifications: [],
    certification_summary: null,
    projects: [],
    publications: [],
    awards: [],
    languages: [],
    career_analysis: null,
    inference_source: "llm",
    inference_model: "claude-opus-5-5",
    inference_status: "complete",
    inference_error: null,
    inferred_at: "2026-11-26T10:00:00Z",
    overrides: [],
    warnings: [],
    source_resume_id: "r1",
    updated_at: "2026-11-26T10:00:00Z",
    ...overrides,
  };
}

/** Mock global fetch; returns the mock so tests can inspect calls. */
export function mockFetch(...responses: Response[]) {
  const fn = vi.fn<typeof fetch>();
  for (const r of responses) fn.mockResolvedValueOnce(r);
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
