// Application packages API: generate, review, approve, reject, regenerate.
import type { Page, PackageAnswer, PackageDetail, PackageDoc, PackageStarted, PackageStatus, PackageSummary } from "@/types";

import { apiFetch, apiUrl } from "./client";

const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const packagesApi = {
  list: (params: { status?: PackageStatus[]; jobId?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    for (const s of params.status ?? []) qs.append("status", s);
    if (params.jobId) qs.set("job_id", params.jobId);
    qs.set("limit", String(params.limit ?? 50));
    if (params.offset) qs.set("offset", String(params.offset));
    return apiFetch<Page<PackageSummary>>(`/packages?${qs.toString()}`);
  },
  get: (id: string) => apiFetch<PackageDetail>(`/packages/${id}`),
  generate: (jobId: string, useLlm = false, includeCoverLetter = true) =>
    post<PackageStarted>("/packages", { job_id: jobId, use_llm: useLlm, include_cover_letter: includeCoverLetter }),
  review: (id: string) => post<PackageDetail>(`/packages/${id}/review`),
  approve: (id: string, notes?: string) => post<PackageDetail>(`/packages/${id}/approve`, { notes: notes || null }),
  reject: (id: string, reason: string) => post<PackageDetail>(`/packages/${id}/reject`, { reason }),
  regenerate: (id: string, useLlm = false, includeCoverLetter = true) =>
    post<PackageStarted>(`/packages/${id}/regenerate`, { use_llm: useLlm, include_cover_letter: includeCoverLetter }),
  markSubmitted: (id: string) => post<PackageDetail>(`/packages/${id}/mark-submitted`),
  updateAnswer: (id: string, answerId: string, answer: string) =>
    apiFetch<PackageAnswer>(`/packages/${id}/answers/${answerId}`, {
      method: "PATCH",
      body: JSON.stringify({ answer }),
    }),
  fileUrl: (id: string, doc: PackageDoc, format: "pdf" | "docx") => apiUrl(`/packages/${id}/files/${doc}.${format}`),
};
