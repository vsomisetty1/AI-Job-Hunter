"use client";

// SWR hooks for resumes, the profile and background tasks.

import useSWR from "swr";

import { ApiError } from "@/lib/api/client";
import { profileApi, resumesApi, tasksApi } from "@/lib/api/resumes";
import type { BackgroundTask, CandidateProfile, Resume, ResumeDetail } from "@/types";

export function useResumes() {
  return useSWR<Resume[]>("resumes", resumesApi.list);
}

export function useResume(id: string | null) {
  return useSWR<ResumeDetail>(id ? ["resume", id] : null, () => resumesApi.get(id as string));
}

/** The profile; polls while generation is pending or running. 404 = no profile yet. */
export function useProfile() {
  return useSWR<CandidateProfile | null>(
    "profile",
    async () => {
      try {
        return await profileApi.get();
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    {
      refreshInterval: (p) =>
        p && (p.inference_status === "pending" || p.inference_status === "running") ? 2000 : 0,
    },
  );
}

const isDone = (t: BackgroundTask | undefined) =>
  !!t && (t.status === "succeeded" || t.status === "failed" || t.status === "cancelled");

/** Polls a background task until it finishes; `onDone` runs once when it does. */
export function useTask(taskId: string | null, onDone?: (task: BackgroundTask) => void) {
  return useSWR<BackgroundTask>(taskId ? ["task", taskId] : null, () => tasksApi.get(taskId!), {
    refreshInterval: (t) => (isDone(t) ? 0 : 1000),
    onSuccess: (t) => {
      if (isDone(t)) onDone?.(t);
    },
  });
}
