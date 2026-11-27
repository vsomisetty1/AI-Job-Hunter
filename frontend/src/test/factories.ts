import { vi } from "vitest";

import type { CandidateProfile, Company, DiscoveryRunDetail, JobDetail, JobSummary, ParsedResume } from "@/types";

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

export function jobSummary(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "j1",
    company_id: "c1",
    company_name: "Acme Robotics",
    source: "greenhouse",
    external_id: "4001",
    title: "Senior Backend Engineer",
    location: "San Francisco, CA",
    remote_type: "hybrid",
    employment_type: "full_time",
    salary_min: 180000,
    salary_max: 220000,
    salary_currency: "USD",
    status: "new",
    url: "https://acme.example/careers?gh_jid=4001",
    posted_at: "2026-11-20T10:00:00Z",
    first_seen_at: "2026-11-26T10:00:00Z",
    last_seen_at: "2026-11-27T10:00:00Z",
    ...overrides,
  };
}

export function jobDetail(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    ...jobSummary(),
    compensation_text: "$180,000 - $220,000 USD",
    description: "Build robots.\n\n• Ship APIs",
    requirements: ["5+ years of Python"],
    apply_url: null,
    dedup_key: "a".repeat(64),
    expired_at: null,
    updated_at: "2026-11-27T10:00:00Z",
    ...overrides,
  };
}

export function company(overrides: Partial<Company> = {}): Company {
  return {
    id: "c1",
    name: "Acme Robotics",
    source: "greenhouse",
    slug: "acme",
    careers_url: "https://job-boards.greenhouse.io/acme",
    is_tracked: true,
    last_crawled_at: null,
    last_crawl_status: null,
    last_error: null,
    consecutive_failures: 0,
    created_at: "2026-11-27T10:00:00Z",
    active_jobs: 0,
    ...overrides,
  };
}

export function discoveryRun(overrides: Partial<DiscoveryRunDetail> = {}): DiscoveryRunDetail {
  return {
    id: "r1",
    trigger: "manual",
    status: "succeeded",
    companies_total: 1,
    companies_succeeded: 1,
    companies_failed: 0,
    jobs_found: 4,
    jobs_inserted: 3,
    jobs_updated: 0,
    jobs_unchanged: 0,
    jobs_skipped: 1,
    jobs_expired: 0,
    error: null,
    started_at: "2026-11-27T10:00:00Z",
    finished_at: "2026-11-27T10:00:02Z",
    duration_ms: 2000,
    details: [],
    ...overrides,
  };
}

/** fetch mock that answers by "METHOD path" (path after /api/v1, query included). */
export function routeFetch(routes: Record<string, () => Response>) {
  const fn = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(String(input));
    const path = url.pathname.replace(/^\/api\/v1/, "") + url.search;
    const key = `${init?.method ?? "GET"} ${path}`;
    const handler = routes[key] ?? routes[`${init?.method ?? "GET"} ${url.pathname.replace(/^\/api\/v1/, "")}`];
    if (!handler) return json({ error: { code: "not_found", message: `no mock for ${key}` } }, 404);
    return handler();
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
