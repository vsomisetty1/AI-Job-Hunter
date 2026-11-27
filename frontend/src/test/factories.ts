import { vi } from "vitest";

import type {
  CandidateProfile,
  Company,
  DiscoveryRunDetail,
  JobDetail,
  JobScore,
  JobSummary,
  PackageDetail,
  ParsedResume,
  ScoringSummary,
  Settings,
  SubmissionDetail,
} from "@/types";

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
    score: 82,
    score_method: "rules",
    filter_reason: null,
    duplicate_of: null,
    ...overrides,
  };
}

export function jobScore(overrides: Partial<JobScore> = {}): JobScore {
  return {
    id: "s1",
    job_id: "j1",
    profile_id: "p1",
    scoring_method: "rules",
    overall_score: 82,
    skills_score: 78,
    seniority_score: 100,
    location_score: 100,
    relevance_score: 90,
    salary_score: null,
    interview_probability: null,
    growth_score: null,
    company_score: null,
    rationale: "Skills: 3 of 4 skills match.",
    matched_skills: ["Python", "PostgreSQL"],
    missing_skills: ["Kubernetes"],
    breakdown: {
      confidence: 0.9,
      components: {
        skills: { score: 78, summary: "3 of 4 skills match; missing Kubernetes", detail: {} },
        salary: { score: null, summary: "Salary not listed", detail: {} },
      },
    },
    model: null,
    prompt_version: null,
    input_tokens: 0,
    output_tokens: 0,
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
    is_current: true,
    ...overrides,
  };
}

export function scoringSummary(overrides: Partial<ScoringSummary> = {}): ScoringSummary {
  return {
    profile_id: "p1",
    jobs_active: 3,
    jobs_unfiltered: 0,
    jobs_passed: 2,
    jobs_rejected: 1,
    jobs_duplicate: 0,
    jobs_scored: 2,
    jobs_claude_scored: 0,
    claude_available: false,
    claude_enabled: false,
    claude_calls_today: 0,
    claude_daily_limit: 100,
    last_run_at: null,
    last_run_status: null,
    task_running: false,
    ...overrides,
  };
}

export function settings(overrides: Partial<Settings> = {}): Settings {
  return {
    preferred_locations: ["San Francisco"],
    remote_preference: "any",
    job_types: [],
    salary_min: null,
    salary_target: null,
    salary_currency: "USD",
    work_authorization: null,
    visa_status: null,
    requires_sponsorship: false,
    excluded_companies: [],
    excluded_keywords: [],
    application_mode: "APPROVAL_MODE",
    auto_apply_threshold: 80,
    daily_application_cap: 10,
    discovery_enabled: true,
    claude_scoring_enabled: false,
    claude_scoring_min_score: 60,
    willing_to_relocate: null,
    extra: {},
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:00:00Z",
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
    filter_result: null,
    filtered_at: null,
    scores: [],
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

export function packageDetail(overrides: Partial<PackageDetail> = {}): PackageDetail {
  return {
    id: "pk1",
    job_id: "j1",
    job_title: "Senior Backend Engineer",
    company_name: "Stripe",
    version_number: 1,
    status: "reviewed",
    score: 84,
    score_method: "rules",
    answers_needing_review: 1,
    error: null,
    generated_at: "2026-11-27T10:00:00Z",
    reviewed_at: "2026-11-27T10:05:00Z",
    approved_at: null,
    rejected_at: null,
    submitted_at: null,
    created_at: "2026-11-27T10:00:00Z",
    updated_at: "2026-11-27T10:05:00Z",
    job: jobSummary(),
    score_snapshot: { overall: 84, method: "rules", rationale: "Skills: 3 of 4 skills match." },
    generation: { use_llm: false, llm_used: false },
    review_notes: null,
    rejection_reason: null,
    application_id: null,
    base_resume: parsedResume(),
    base_resume_version_id: "v1",
    tailored_resume: {
      id: "v2",
      resume_id: "r1",
      version_number: 2,
      base_version_id: "v1",
      content: parsedResume({ skills: ["Python", "Go"] }),
      changes: [
        {
          section: "skills",
          item: null,
          field: "order",
          before: ["Go", "Python"],
          after: ["Python", "Go"],
          reason: "Moved the skills this job asks for to the front: Python",
          at: "2026-11-27T10:00:00Z",
        },
        {
          section: "summary",
          item: null,
          field: "text",
          before: "Backend engineer.",
          after: "Senior Backend Engineer with 5+ years of experience in Python. Backend engineer.",
          reason: "Opens with the role, experience and skills this job asks for",
          at: "2026-11-27T10:00:00Z",
        },
      ],
      tailoring: {
        method: "rules",
        matched_skills: ["Python"],
        missing_skills: ["Kubernetes"],
        notes: ["The posting asks for Kubernetes, which your resume does not mention."],
        rejected_rewrites: [],
      },
      ats_keywords: ["Python"],
      change_summary: "Tailored by reordering: 2 changes.",
      has_pdf: true,
      has_docx: true,
      created_at: "2026-11-27T10:00:00Z",
    },
    cover_letter: {
      id: "cl1",
      version_number: 1,
      content: "Dear Stripe hiring team,\n\nI am applying for the Senior Backend Engineer role at Stripe.",
      word_count: 182,
      method: "rules",
      model: null,
      generation: { notes: ["The sentence about why the role fits is general; make it personal before sending."] },
      has_pdf: true,
      has_docx: true,
      created_at: "2026-11-27T10:00:00Z",
    },
    answers: [
      {
        id: "a1",
        question: "Will you now or in the future require visa sponsorship?",
        question_key: "sponsorship",
        answer: "No, I do not require visa sponsorship.",
        source: "settings",
        confidence: 0.95,
        needs_review: false,
        evidence: [{ source: "settings", fact: "requires_sponsorship false" }],
        updated_at: "2026-11-27T10:00:00Z",
      },
      {
        id: "a2",
        question: "Why do you want to work at Stripe?",
        question_key: "why_company",
        answer: "The role lines up with the work I do best.",
        source: "rules",
        confidence: 0.5,
        needs_review: true,
        evidence: [{ source: "job", fact: "Senior Backend Engineer at Stripe" }],
        updated_at: "2026-11-27T10:00:00Z",
      },
    ],
    ...overrides,
  };
}

export function submission(overrides: Partial<SubmissionDetail> = {}): SubmissionDetail {
  return {
    id: "sb1",
    application_id: "ap1",
    package_id: "pk1",
    job_id: "j1",
    job_title: "Senior Backend Engineer",
    company_name: "Stripe",
    job_status: "shortlisted",
    platform: "greenhouse",
    apply_url: "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=1",
    mode: "APPROVAL_MODE",
    status: "waiting_for_review",
    step: "review",
    attempts: 1,
    error: null,
    error_kind: null,
    live: true,
    ready: false,
    missing_count: 1,
    problem_count: 0,
    queued_at: "2026-11-27T10:00:00Z",
    started_at: "2026-11-27T10:00:01Z",
    review_ready_at: "2026-11-27T10:00:20Z",
    confirmed_at: null,
    submitted_at: null,
    failed_at: null,
    cancelled_at: null,
    updated_at: "2026-11-27T10:00:20Z",
    review: {
      resume: { status: "uploaded", file: "Jordan_Rivera_Resume.pdf", field: "Resume/CV" },
      cover_letter: { status: "uploaded", file: "Jordan_Rivera_Cover_Letter.pdf", field: "Cover Letter" },
      answers: [
        { key: "first_name", label: "First Name", kind: "text", required: true, status: "filled", value: "Jordan", source: "resume", reason: "" },
        { key: "gender", label: "Gender", kind: "combobox", required: false, status: "filled", value: "(voluntary: declined)", source: "rule", reason: "", sensitive: true },
      ],
      missing: [{ key: "team", label: "Which team?", kind: "select", reason: "No fact answers this question.", status: "needs_you" }],
      problems: [],
      left_for_you: [
        { key: "team", label: "Which team?", kind: "select", required: true, status: "needs_you", value: "", source: "", reason: "No fact answers this question." },
        { key: "privacy", label: "I agree to the privacy policy", kind: "checkbox", required: false, status: "consent", value: "", source: "", reason: "Consent boxes are left for you." },
      ],
      captcha: false,
      fields_total: 5,
      form_changed: false,
      ready: false,
    },
    edits: {},
    checkpoint: {},
    screenshots: [{ index: 1, step: "review", label: "Form filled, waiting for your review", at: "2026-11-27T10:00:20Z" }],
    confirmation_text: null,
    recovery_hint: null,
    editable_fields: [
      { key: "first_name", label: "First Name", kind: "text", required: true, status: "filled", value: "Jordan", reason: "", options: [], edited: false },
      { key: "team", label: "Which team?", kind: "select", required: true, status: "needs_you", value: "", reason: "", options: ["Payments", "Platform"], edited: false },
    ],
    ...overrides,
  };
}
