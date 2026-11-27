// Shared TS types mirroring the backend API schemas (backend/app/schemas).

export type FileType = "pdf" | "docx";
export type VersionKind = "original" | "parsed" | "tailored";
export type ParseStatus = "pending" | "parsed" | "failed";
export type InferenceStatus = "none" | "pending" | "running" | "complete" | "failed";

export interface ContactInfo {
  name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  linkedin: string | null;
  github: string | null;
  portfolio: string | null;
  other_links: string[];
}

export interface ExperienceEntry {
  title: string | null;
  company: string | null;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  bullets: string[];
  skills: string[];
}

export interface EducationEntry {
  institution: string | null;
  degree: string | null;
  field_of_study: string | null;
  start_date: string | null;
  end_date: string | null;
  gpa: string | null;
  honors: string[];
}

export interface CertificationEntry {
  name: string;
  issuer: string | null;
  date: string | null;
  expires: string | null;
  credential_id: string | null;
}

export interface ProjectEntry {
  name: string;
  description: string | null;
  url: string | null;
  technologies: string[];
  bullets: string[];
}

export interface PublicationEntry {
  title: string;
  venue: string | null;
  date: string | null;
  url: string | null;
}

export interface AwardEntry {
  title: string;
  issuer: string | null;
  date: string | null;
  description: string | null;
}

export interface SkillGroup {
  name: string;
  skills: string[];
}

export interface ParseMeta {
  method: "deterministic" | "llm_assisted" | "user_edit";
  parser_version: string;
  confidence: number;
  section_confidence: { section: string; score: number }[];
  llm_sections: string[];
  warnings: string[];
}

export interface ParsedResume {
  contact: ContactInfo;
  summary: string | null;
  experience: ExperienceEntry[];
  education: EducationEntry[];
  skills: string[];
  skill_groups: SkillGroup[];
  certifications: CertificationEntry[];
  projects: ProjectEntry[];
  publications: PublicationEntry[];
  awards: AwardEntry[];
  languages: string[];
  other_sections: { title: string; lines: string[] }[];
  meta: ParseMeta;
}

export interface ResumeVersionSummary {
  id: string;
  version_number: number;
  kind: VersionKind;
  source: "upload" | "parser" | "user_edit" | "tailoring";
  job_id: string | null;
  target_role: string | null;
  target_company: string | null;
  change_summary: string | null;
  ats_keywords: string[];
  created_at: string;
}

export interface ResumeVersion extends ResumeVersionSummary {
  content: Record<string, unknown>;
}

export interface Resume {
  id: string;
  filename: string;
  file_type: FileType;
  size_bytes: number;
  is_primary: boolean;
  parse_status: ParseStatus;
  parse_method: string | null;
  parse_error: string | null;
  parsed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeDetail extends Resume {
  parsed: ParsedResume | null;
  parsed_version_id: string | null;
  versions: ResumeVersionSummary[];
}

export interface UploadResponse {
  resume: ResumeDetail;
  task_id: string | null;
}

export interface RoleSuggestion {
  title: string;
  rationale: string;
}

export interface CareerHistoryItem {
  title: string | null;
  company: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  duration_months: number | null;
}

export interface CareerAnalysis {
  narrative: string;
  trajectory: string;
  strengths: string[];
  gaps: string[];
  recommended_focus: string[];
}

export interface CandidateProfile {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  linkedin_url: string | null;
  portfolio_url: string | null;
  headline: string | null;
  summary: string | null;
  seniority: string | null;
  experience_level: string | null;
  years_of_experience: number | null;
  skills: string[];
  skill_groups: SkillGroup[];
  industries: string[];
  inferred_roles: string[];
  transferable_roles: RoleSuggestion[];
  career_history: CareerHistoryItem[];
  education: EducationEntry[];
  education_summary: string | null;
  certifications: CertificationEntry[];
  certification_summary: string | null;
  projects: ProjectEntry[];
  publications: PublicationEntry[];
  awards: AwardEntry[];
  languages: string[];
  career_analysis: CareerAnalysis | null;
  inference_source: "deterministic" | "llm";
  inference_model: string | null;
  inference_status: InferenceStatus;
  inference_error: string | null;
  inferred_at: string | null;
  overrides: string[];
  warnings: string[];
  source_resume_id: string | null;
  updated_at: string;
}

export type ProfileUpdate = Partial<
  Pick<
    CandidateProfile,
    | "full_name"
    | "email"
    | "phone"
    | "location"
    | "linkedin_url"
    | "portfolio_url"
    | "headline"
    | "summary"
    | "seniority"
    | "years_of_experience"
    | "skills"
    | "industries"
    | "inferred_roles"
    | "transferable_roles"
    | "education_summary"
    | "certification_summary"
  >
>;

export interface TaskAccepted {
  task_id: string;
  status: string;
  detail: string;
}

export interface BackgroundTask {
  id: string;
  name: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

// ------------------------------------------------------------ Phase 5: discovery
export type JobSource = "greenhouse" | "lever" | "ashby";
export type RemoteType = "remote" | "hybrid" | "onsite" | "unknown";
export type JobStatus = "new" | "filtered" | "scored" | "shortlisted" | "skipped" | "applied" | "expired";

export interface JobSummary {
  id: string;
  company_id: string;
  company_name: string;
  source: JobSource;
  external_id: string;
  title: string;
  location: string | null;
  remote_type: RemoteType;
  employment_type: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  status: JobStatus;
  url: string;
  posted_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  /** Effective score for the active profile: Claude when current, else rules. */
  score: number | null;
  score_method: ScoringMethod | null;
  filter_reason: string | null;
  duplicate_of: string | null;
}

export interface JobDetail extends JobSummary {
  compensation_text: string | null;
  description: string;
  requirements: string[];
  apply_url: string | null;
  dedup_key: string;
  expired_at: string | null;
  updated_at: string;
  filter_result: FilterResult | null;
  filtered_at: string | null;
  /** Rule-based score first, then Claude's (if any). */
  scores: JobScore[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface JobSearch {
  q?: string;
  source?: JobSource | "";
  company_id?: string;
  remote_type?: RemoteType | "";
  status?: JobStatus | "";
  include_expired?: boolean;
  filter_state?: FilterState;
  min_score?: number;
  sort?: JobSort;
  limit?: number;
  offset?: number;
}

export interface JobRaw {
  source: JobSource;
  external_id: string;
  raw: unknown;
}

export interface Company {
  id: string;
  name: string;
  source: JobSource;
  slug: string;
  careers_url: string | null;
  is_tracked: boolean;
  last_crawled_at: string | null;
  last_crawl_status: "ok" | "error" | "not_found" | null;
  last_error: string | null;
  consecutive_failures: number;
  created_at: string;
  active_jobs: number;
}

export interface DirectoryEntry {
  source: JobSource;
  slug: string;
  name: string;
  added: boolean;
}

export type RunStatus = "running" | "succeeded" | "partial" | "failed" | "cancelled";

export interface DiscoveryRun {
  id: string;
  trigger: "manual" | "scheduled";
  status: RunStatus;
  companies_total: number;
  companies_succeeded: number;
  companies_failed: number;
  jobs_found: number;
  jobs_inserted: number;
  jobs_updated: number;
  jobs_unchanged: number;
  jobs_skipped: number;
  jobs_expired: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface CompanyOutcome {
  company_id: string;
  source: JobSource;
  slug: string;
  name: string;
  status: "ok" | "error" | "not_found";
  found: number;
  invalid: number;
  inserted: number;
  updated: number;
  unchanged: number;
  skipped: number;
  expired: number;
  pages: number;
  duration_ms: number;
  error: string | null;
  notes: string[];
  skip_reasons: Record<string, number>;
}

export interface DiscoveryRunDetail extends DiscoveryRun {
  details: CompanyOutcome[];
}

export interface DiscoveryStarted {
  run_id: string;
  task_id: string;
  status: string;
  detail: string;
}

export interface SourceHealth {
  source: JobSource;
  display_name: string;
  companies_tracked: number;
  companies_failing: number;
  last_success_at: string | null;
  jobs_active: number;
  probe: {
    ok: boolean;
    board: string;
    latency_ms: number;
    jobs_visible: number | null;
    error: string | null;
  } | null;
}

// ------------------------------------------------- Phase 6: filtering & scoring
export type ScoringMethod = "rules" | "claude";
export type FilterState = "all" | "passed" | "rejected" | "pending";
export type JobSort = "score" | "newest" | "posted" | "title" | "company";
export type EmploymentType = "full_time" | "part_time" | "contract" | "temporary" | "internship";
export type RemotePreference = "remote_only" | "hybrid" | "onsite" | "any";

export interface FilterCheck {
  rule: string;
  passed: boolean;
  reason: string;
}

export interface FilterResult {
  passed: boolean;
  version: string;
  checks: FilterCheck[];
}

export interface ScoreComponent {
  score: number | null;
  summary: string;
  detail: Record<string, unknown>;
}

export interface JobScore {
  id: string;
  job_id: string;
  profile_id: string;
  scoring_method: ScoringMethod;
  overall_score: number;
  skills_score: number | null;
  seniority_score: number | null;
  location_score: number | null;
  relevance_score: number | null;
  salary_score: number | null;
  interview_probability: number | null;
  growth_score: number | null;
  company_score: number | null;
  rationale: string | null;
  matched_skills: string[];
  missing_skills: string[];
  /** rules: {version, overall, confidence, weights, components}; claude: {strengths, concerns, ...} */
  breakdown: {
    confidence?: number;
    weights?: Record<string, number>;
    components?: Record<string, ScoreComponent>;
    strengths?: string[];
    concerns?: string[];
    [key: string]: unknown;
  };
  model: string | null;
  prompt_version: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  updated_at: string;
  is_current: boolean;
}

export interface ScoringSummary {
  profile_id: string | null;
  jobs_active: number;
  jobs_unfiltered: number;
  jobs_passed: number;
  jobs_rejected: number;
  jobs_duplicate: number;
  jobs_scored: number;
  jobs_claude_scored: number;
  claude_available: boolean;
  claude_enabled: boolean;
  claude_calls_today: number;
  claude_daily_limit: number;
  last_run_at: string | null;
  last_run_status: string | null;
  task_running: boolean;
}

export interface ScoringStarted {
  task_id: string;
  status: string;
  detail: string;
}

export interface Settings {
  preferred_locations: string[];
  remote_preference: RemotePreference;
  job_types: EmploymentType[];
  salary_min: number | null;
  salary_target: number | null;
  salary_currency: string;
  work_authorization: string | null;
  visa_status: string | null;
  requires_sponsorship: boolean;
  excluded_companies: string[];
  excluded_keywords: string[];
  application_mode: "APPROVAL_MODE" | "AUTONOMOUS_MODE";
  auto_apply_threshold: number;
  daily_application_cap: number;
  discovery_enabled: boolean;
  claude_scoring_enabled: boolean;
  claude_scoring_min_score: number;
  extra: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type SettingsUpdate = Partial<Omit<Settings, "created_at" | "updated_at">>;
