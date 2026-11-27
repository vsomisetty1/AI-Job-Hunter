// Resumes, profile and background-task API calls.

import type {
  BackgroundTask,
  CandidateProfile,
  ParsedResume,
  ProfileUpdate,
  Resume,
  ResumeDetail,
  ResumeVersion,
  TaskAccepted,
  UploadResponse,
} from "@/types";

import { apiFetch, apiUrl } from "./client";

export const MAX_UPLOAD_MB = 10;
export const ACCEPTED_TYPES: Record<string, "pdf" | "docx"> = {
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
};

/** Client-side pre-check; the server re-validates everything. */
export function checkResumeFile(file: File, maxMb = MAX_UPLOAD_MB): string | null {
  const ext = file.name.toLowerCase().split(".").pop();
  if (!(ext === "pdf" || ext === "docx") && !(file.type in ACCEPTED_TYPES)) {
    return "Only PDF and DOCX files are supported.";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > maxMb * 1024 * 1024) return `The file is larger than ${maxMb} MB.`;
  return null;
}

export const resumesApi = {
  list: () => apiFetch<Resume[]>("/resumes"),
  get: (id: string) => apiFetch<ResumeDetail>(`/resumes/${id}`),
  upload: (file: File, makePrimary = false) => {
    const form = new FormData();
    form.append("file", file);
    form.append("make_primary", String(makePrimary));
    return apiFetch<UploadResponse>("/resumes", { method: "POST", body: form });
  },
  remove: (id: string) => apiFetch<void>(`/resumes/${id}`, { method: "DELETE" }),
  makePrimary: (id: string) =>
    apiFetch<TaskAccepted>(`/resumes/${id}/primary`, { method: "POST" }),
  reparse: (id: string, useLlm = true) =>
    apiFetch<TaskAccepted>(`/resumes/${id}/reparse`, {
      method: "POST",
      body: JSON.stringify({ use_llm: useLlm }),
    }),
  saveParsed: (id: string, data: ParsedResume, changeSummary?: string) =>
    apiFetch<ResumeVersion>(`/resumes/${id}/parsed`, {
      method: "PUT",
      body: JSON.stringify({ data, change_summary: changeSummary || null }),
    }),
  version: (id: string, versionId: string) =>
    apiFetch<ResumeVersion>(`/resumes/${id}/versions/${versionId}`),
  downloadUrl: (id: string) => apiUrl(`/resumes/${id}/download`),
};

export const profileApi = {
  get: () => apiFetch<CandidateProfile>("/profile"),
  update: (patch: ProfileUpdate) =>
    apiFetch<CandidateProfile>("/profile", { method: "PATCH", body: JSON.stringify(patch) }),
  regenerate: (opts: { keep_overrides?: boolean; use_llm?: boolean; resume_id?: string } = {}) =>
    apiFetch<TaskAccepted>("/profile/regenerate", { method: "POST", body: JSON.stringify(opts) }),
};

export const tasksApi = {
  get: (id: string) => apiFetch<BackgroundTask>(`/system/tasks/${id}`),
};
