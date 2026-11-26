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
