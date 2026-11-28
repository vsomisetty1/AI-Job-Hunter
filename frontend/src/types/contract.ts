// Compile-time API contract: the frontend's hand-written types (./index.ts)
// against the backend's schemas as generated in ./api.gen.ts. Checked by
// `npm run typecheck` (tsc), so it fails CI when they drift apart.
//
// For a response type:   what the backend sends must fit the frontend type,
//                        and the frontend may not expect fields that do not exist.
// For a request body:    what the frontend sends must fit the backend schema,
//                        and may not contain fields the backend does not accept.
//
// A failure reads "Type 'false' does not satisfy the constraint 'true'" or names
// the offending fields: compare the two types on that line, then fix index.ts
// (or the backend), and regenerate api.gen.ts with scripts/gen_api_contract.py.
// Shapes the backend leaves untyped (dict[str, Any]) cannot be checked here;
// docs/TESTING.md lists them.

import type * as api from "./api.gen";
import type * as ui from "./index";

type Fits<From, To> = [From] extends [To] ? true : false;
type UnknownKeys<T, Known> = Exclude<keyof T, keyof Known>;

/** Backend response B is usable as the frontend type F. */
type Response<B, F> =
  Fits<B, F> extends true
    ? [UnknownKeys<F, B>] extends [never]
      ? true
      : { frontendExpectsFieldsTheBackendDoesNotSend: UnknownKeys<F, B> }
    : false;

/** Frontend request body F is accepted by the backend schema B. */
type Request<F, B> =
  Fits<F, B> extends true
    ? [UnknownKeys<F, B>] extends [never]
      ? true
      : { frontendSendsFieldsTheBackendRejects: UnknownKeys<F, B> }
    : false;

type Expect<T extends true> = T;

export type ResponseContract = [
  // Resumes and profile
  Expect<Response<api.ContactInfo, ui.ContactInfo>>,
  Expect<Response<api.ExperienceEntry, ui.ExperienceEntry>>,
  Expect<Response<api.EducationEntry, ui.EducationEntry>>,
  Expect<Response<api.CertificationEntry, ui.CertificationEntry>>,
  Expect<Response<api.ProjectEntry, ui.ProjectEntry>>,
  Expect<Response<api.PublicationEntry, ui.PublicationEntry>>,
  Expect<Response<api.AwardEntry, ui.AwardEntry>>,
  Expect<Response<api.SkillGroup, ui.SkillGroup>>,
  Expect<Response<api.ParseMeta, ui.ParseMeta>>,
  Expect<Response<api.ParsedResume, ui.ParsedResume>>,
  Expect<Response<api.ResumeVersionSummary, ui.ResumeVersionSummary>>,
  Expect<Response<api.ResumeVersionRead, ui.ResumeVersion>>,
  Expect<Response<api.ResumeRead, ui.Resume>>,
  Expect<Response<api.ResumeDetail, ui.ResumeDetail>>,
  Expect<Response<api.UploadResponse, ui.UploadResponse>>,
  Expect<Response<api.RoleSuggestion, ui.RoleSuggestion>>,
  Expect<Response<api.CareerHistoryItem, ui.CareerHistoryItem>>,
  Expect<Response<api.CareerAnalysisOutput, ui.CareerAnalysis>>,
  Expect<Response<api.CandidateProfileRead, ui.CandidateProfile>>,
  Expect<Response<api.TaskAccepted, ui.TaskAccepted>>,
  Expect<Response<api.BackgroundTask, ui.BackgroundTask>>,
  // Jobs, companies, discovery, scoring
  Expect<Response<api.JobSummary, ui.JobSummary>>,
  Expect<Response<api.JobDetail, ui.JobDetail>>,
  Expect<Response<api.Page_JobSummary_, ui.Page<ui.JobSummary>>>,
  Expect<Response<api.CompanyWithStats, ui.Company>>,
  Expect<Response<api.DirectoryEntryRead, ui.DirectoryEntry>>,
  Expect<Response<api.DiscoveryRunSummary, ui.DiscoveryRun>>,
  Expect<Response<api.Page_DiscoveryRunSummary_, ui.Page<ui.DiscoveryRun>>>,
  Expect<Response<api.DiscoveryRunDetail, ui.DiscoveryRunDetail>>,
  Expect<Response<api.DiscoveryStarted, ui.DiscoveryStarted>>,
  Expect<Response<api.SourceHealth, ui.SourceHealth>>,
  Expect<Response<api.FilterCheck, ui.FilterCheck>>,
  Expect<Response<api.FilterResult, ui.FilterResult>>,
  Expect<Response<api.JobScoreRead, ui.JobScore>>,
  Expect<Response<api.ScoringSummary, ui.ScoringSummary>>,
  Expect<Response<api.ScoringStarted, ui.ScoringStarted>>,
  Expect<Response<api.SettingsRead, ui.Settings>>,
  // Packages
  Expect<Response<api.ResumeChange, ui.ResumeChange>>,
  Expect<Response<api.TailoredResumeRead, ui.TailoredResume>>,
  Expect<Response<api.CoverLetterRead, ui.CoverLetter>>,
  Expect<Response<api.AnswerRead, ui.PackageAnswer>>,
  Expect<Response<api.PackageSummary, ui.PackageSummary>>,
  Expect<Response<api.Page_PackageSummary_, ui.Page<ui.PackageSummary>>>,
  Expect<Response<api.PackageDetail, ui.PackageDetail>>,
  Expect<Response<api.PackageStarted, ui.PackageStarted>>,
  // Automation
  Expect<Response<api.SubmissionStarted, ui.SubmissionStarted>>,
  Expect<Response<api.SubmissionSummary, ui.SubmissionSummary>>,
  Expect<Response<api.Page_SubmissionSummary_, ui.Page<ui.SubmissionSummary>>>,
  Expect<Response<api.SubmissionDetail, ui.SubmissionDetail>>,
  Expect<Response<api.ReadyPackage, ui.ReadyPackage>>,
  Expect<Response<api.AutomationQueue, ui.AutomationQueue>>,
  Expect<Response<api.AutomationLogRead, ui.AutomationLog>>,
  Expect<Response<api.Page_AutomationLogRead_, ui.Page<ui.AutomationLog>>>,
  Expect<Response<api.AutomationStatus, ui.AutomationStatus>>,
  // Outcomes and insights
  Expect<Response<api.InterviewEventRead, ui.InterviewEvent>>,
  Expect<Response<api.PipelineItem, ui.PipelineItem>>,
  Expect<Response<api.TimelineEntry, ui.TimelineEntry>>,
  Expect<Response<api.ApplicationOutcomes, ui.ApplicationOutcomes>>,
  Expect<Response<api.InsightRead, ui.Insight>>,
  Expect<Response<api.RecommendationRead, ui.Recommendation>>,
  Expect<Response<api.InsightsReport, ui.InsightsReport>>,
  Expect<Response<api.HistoryPoint, ui.HistoryPoint>>,
  // Agent activity
  Expect<Response<api.AgentRunRead, ui.AgentRun>>,
  Expect<Response<api.Page_AgentRunRead_, ui.Page<ui.AgentRun>>>,
  Expect<Response<api.AgentStat, ui.AgentStat>>,
  Expect<Response<api.AgentActivitySummary, ui.AgentActivitySummary>>,
];

export type RequestContract = [
  Expect<Request<ui.SettingsUpdate, api.SettingsUpdateInput>>,
  Expect<Request<ui.ProfileUpdate, api.CandidateProfileUpdateInput>>,
];
