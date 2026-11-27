"use client";

// SWR hooks for outcome tracking and analytics.
import useSWR from "swr";

import { insightsApi, outcomesApi } from "@/lib/api/insights";

export const usePipeline = () => useSWR("pipeline", () => outcomesApi.pipeline());
export const useOutcomes = (id: string | null) =>
  useSWR(id ? ["outcomes", id] : null, () => outcomesApi.get(id as string));
export const useTimeline = () => useSWR("timeline", () => outcomesApi.timeline(300));
export const useAnalytics = () => useSWR("analytics", () => insightsApi.summary());
export const useCompanyAnalytics = () => useSWR("analytics-companies", () => insightsApi.companies());
export const useBoardAnalytics = () => useSWR("analytics-boards", () => insightsApi.boards());
export const useResumeAnalytics = () => useSWR("analytics-resumes", () => insightsApi.resumes());
export const useInsightsReport = () => useSWR("insights", () => insightsApi.insights());
export const useRecommendations = (includeDismissed: boolean) =>
  useSWR(["recommendations", includeDismissed], () => insightsApi.recommendations(includeDismissed));
export const useLearningHistory = () => useSWR("learning-history", () => insightsApi.history());
