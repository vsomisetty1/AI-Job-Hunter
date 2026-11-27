import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, routeFetch } from "@/test/factories";
import { renderSWR } from "@/test/swr";
import type {
  AnalyticsSummary,
  ApplicationOutcomes,
  CompanyStat,
  PipelineItem,
  RateStat,
  Recommendation,
  SegmentStat,
} from "@/types";

import { AnalyticsDashboard } from "./AnalyticsDashboard";
import { BoardPerformance } from "./BoardPerformance";
import { CompanyInsights } from "./CompanyInsights";
import { InterviewPipeline } from "./InterviewPipeline";
import { OutcomeTimeline } from "./OutcomeTimeline";
import { RecommendationsPage } from "./RecommendationsPage";
import { ResumePerformance } from "./ResumePerformance";

afterEach(() => vi.unstubAllGlobals());

const calls = (fetch: ReturnType<typeof routeFetch>, method: string) =>
  fetch.mock.calls.filter((c) => ((c[1] as RequestInit | undefined)?.method ?? "GET") === method);
const body = (call: unknown[]) => JSON.parse(String((call[1] as RequestInit).body));

const rate = (k: number, n: number): RateStat => ({ k, n, rate: n ? k / n : null, low: 0.1, high: 0.7 });
const segment = (key: string, over: Partial<SegmentStat> = {}): SegmentStat => ({
  key,
  label: key,
  packages: 12,
  submitted: 12,
  responded: 6,
  interviewed: 5,
  offered: 1,
  rejected: 1,
  response_rate: rate(6, 12),
  interview_rate: rate(5, 12),
  offer_rate: rate(1, 12),
  median_days_to_response: 5,
  ...over,
});

function summary(over: Partial<AnalyticsSummary["overview"]> = {}): AnalyticsSummary {
  return {
    computed_at: "2026-11-27T12:00:00Z",
    overview: {
      packages: 14, approved: 13, submitted: 12, responded: 6, interviewed: 5, offered: 1, rejected: 1,
      withdrawn: 0, awaiting_reply: 1, no_reply_after_14_days: 5, response_rate: rate(6, 12),
      interview_rate: rate(5, 12), offer_rate: rate(1, 12), approval_rate: rate(13, 14),
      submission_rate: rate(12, 13), interview_to_offer: rate(1, 5), median_days_to_response: 5,
      enough_data: true, min_sample: 10, ...over,
    },
    funnel: [
      { stage: "generated", label: "Package generated", count: 14, from_previous: null, from_start: rate(14, 14) },
      { stage: "submitted", label: "Application submitted", count: 12, from_previous: rate(12, 14), from_start: rate(12, 14) },
    ],
    score_accuracy: {
      scored_submitted: 12,
      bands: [segment("85+")],
      interviewed: { auc: 0.81, positives: 5, negatives: 7, mean_score_positive: 88, mean_score_negative: 70, enough_data: true, verdict: "scores predict outcomes well" },
      responded: { auc: 0.7, positives: 6, negatives: 6, mean_score_positive: 85, mean_score_negative: 72, enough_data: true, verdict: "scores predict outcomes well" },
    },
    skill_correlations: [{ skill: "Go", asked: 8, have: rate(4, 5), lack: rate(0, 3), lift: null, p_value: 0.04 }],
    by_family: [segment("Backend")],
    by_remote: [segment("Remote")],
    by_score_band: [segment("85+")],
  };
}

const report = {
  status: "ok",
  message: "1 insight(s) from 12 submitted applications; 9 comparisons were tested and only those that held up are shown.",
  comparisons_tested: 9,
  insights: [
    {
      key: "platform:greenhouse:interviewed", kind: "comparison",
      title: "Greenhouse jobs got an interview 5.0x as often as jobs on other boards",
      detail: "5 of 6 (83%) vs 1 of 6 (17%) for jobs on other boards. Fisher exact p = 0.080.",
      confidence: "low", direction: "better", dimension: "platform", segment: "greenhouse",
      outcome: "interviewed", evidence: {},
    },
  ],
};

function pipelineItem(over: Partial<PipelineItem> = {}): PipelineItem {
  return {
    application_id: "ap1", job_id: "j1", job_title: "Backend Engineer", company_id: "c1", company_name: "Stripe",
    industry: null, platform: "greenhouse", package_id: "pk1", status: "submitted", current_stage: null,
    next_scheduled: null, submitted_at: "2026-11-01T10:00:00Z", responded_at: null, first_interview_at: null,
    offer_at: null, rejected_at: null, withdrawn_at: null, days_since_submitted: 26, events: 0, ...over,
  };
}

function outcomes(over: Partial<ApplicationOutcomes> = {}): ApplicationOutcomes {
  return { ...pipelineItem(), interview_events: [], timeline: [], ...over };
}

describe("AnalyticsDashboard", () => {
  it("shows rates with their counts, the funnel, insights and score accuracy", async () => {
    routeFetch({
      "GET /insights/summary": () => json(summary()),
      "GET /insights": () => json(report),
      "GET /insights/history": () => json([]),
    });
    renderSWR(<AnalyticsDashboard />);
    expect(await screen.findByText("42%")).toBeInTheDocument(); // interview rate 5/12
    expect(screen.getAllByText(/5 of 12/).length).toBeGreaterThan(0);
    expect(screen.getByText("Package generated")).toBeInTheDocument();
    expect(await screen.findByText(/Greenhouse jobs got an interview 5.0x/)).toBeInTheDocument();
    expect(screen.getByText(/9 comparisons were tested/)).toBeInTheDocument();
    expect(screen.getByText("scores predict outcomes well")).toBeInTheDocument();
    expect(screen.getAllByText("No history yet")).toHaveLength(3); // one small multiple per rate
  });

  it("says when there is not enough data, and runs the Learning Agent", async () => {
    const fetch = routeFetch({
      "GET /insights/summary": () => json(summary({ submitted: 3, enough_data: false })),
      "GET /insights": () => json({ ...report, status: "insufficient_data", insights: [] }),
      "GET /insights/history": () => json([]),
      "POST /insights/refresh": () => json({ stored: true, records: 3, computed_at: "2026-11-27T12:00:00Z" }),
    });
    renderSWR(<AnalyticsDashboard />);
    expect(await screen.findByText(/3 submitted application\(s\) so far/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run the Learning Agent" }));
    expect(await screen.findByText(/a new snapshot was saved/)).toBeInTheDocument();
    expect(calls(fetch, "POST")).toHaveLength(1);
  });
});

describe("InterviewPipeline", () => {
  it("groups applications by stage and records an outcome", async () => {
    const fetch = routeFetch({
      "GET /applications": () =>
        json([
          pipelineItem(),
          pipelineItem({ application_id: "ap2", job_title: "Platform Engineer", status: "interview", current_stage: "phone_screen", responded_at: "2026-11-05T10:00:00Z" }),
        ]),
      "GET /applications/ap1": () => json(outcomes()),
      "POST /applications/ap1/events": () => json(outcomes({ status: "rejected" }), 201),
    });
    renderSWR(<InterviewPipeline />);
    const waiting = await screen.findByRole("region", { name: "Waiting for a reply" });
    expect(within(waiting).getByText("Backend Engineer")).toBeInTheDocument();
    const interviewing = screen.getByRole("region", { name: "Interviewing" });
    expect(within(interviewing).getByText("Phone screen")).toBeInTheDocument();

    await userEvent.click(within(waiting).getByRole("button", { name: /Backend Engineer/ }));
    await screen.findByText("Nothing recorded yet.");
    await userEvent.selectOptions(screen.getByLabelText("Stage"), "rejection");
    // A rejection has either happened or not: the status is fixed to completed.
    expect(screen.getByLabelText("Status")).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Notes"), "Form email");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const sent = body(calls(fetch, "POST")[0]);
    expect(sent.stage).toBe("rejection");
    expect(sent.status).toBe("completed");
    expect(sent.notes).toBe("Form email");
    expect(new Date(sent.occurred_at).toString()).not.toBe("Invalid Date");
  });

  it("updates and deletes recorded events", async () => {
    const event = {
      id: "e1", application_id: "ap1", stage: "phone_screen" as const, status: "scheduled" as const,
      occurred_at: "2026-11-30T15:00:00Z", notes: null, created_at: "2026-11-20T10:00:00Z", updated_at: "2026-11-20T10:00:00Z",
    };
    const fetch = routeFetch({
      "GET /applications": () => json([pipelineItem({ status: "interview", current_stage: "phone_screen" })]),
      "GET /applications/ap1": () => json(outcomes({ interview_events: [event] })),
      "PATCH /applications/ap1/events/e1": () => json(outcomes()),
      "DELETE /applications/ap1/events/e1": () => new Response(null, { status: 204 }),
    });
    renderSWR(<InterviewPipeline />);
    await userEvent.click(await screen.findByRole("button", { name: /Backend Engineer/ }));
    await userEvent.selectOptions(await screen.findByLabelText("Status of Phone screen"), "completed");
    expect(body(calls(fetch, "PATCH")[0])).toEqual({ status: "completed" });
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(calls(fetch, "DELETE")).toHaveLength(1);
  });

  it("explains an empty pipeline", async () => {
    routeFetch({ "GET /applications": () => json([]) });
    renderSWR(<InterviewPipeline />);
    expect(await screen.findByText(/No submitted applications yet/)).toBeInTheDocument();
  });
});

describe("Recommendations", () => {
  const rec: Recommendation = {
    key: "min-score:85", category: "targeting", priority: "high", title: "Focus on jobs scoring 85 or more",
    rationale: "Jobs scoring 85+ got an interview 3.0x as often: 6 of 10 (60%) vs 2 of 10 (20%).",
    action_label: "Show jobs scoring 85+", action_href: "/jobs?min_score=85", based_on: [], evidence: {}, state: null,
  };

  it("shows the rationale and the action, and can be dismissed", async () => {
    const fetch = routeFetch({
      "GET /insights/recommendations": () => json([rec]),
      "GET /insights": () => json(report),
      "PUT /insights/recommendations/min-score%3A85/state": () => json({ key: rec.key, state: "dismissed" }),
    });
    renderSWR(<RecommendationsPage />);
    expect(await screen.findByText(/6 of 10 \(60%\) vs 2 of 10/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Show jobs scoring 85+" })).toHaveAttribute("href", "/jobs?min_score=85");
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(body(calls(fetch, "PUT")[0])).toEqual({ state: "dismissed" });
    expect(String(calls(fetch, "PUT")[0][0])).toContain("min-score%3A85");
  });
});

describe("Company, resume, board and timeline pages", () => {
  it("lets you set a company's industry", async () => {
    const company: CompanyStat = { ...segment("c1", { label: "Stripe" }), company_id: "c1", industry: null, platform: "greenhouse" };
    const fetch = routeFetch({
      "GET /insights/companies": () => json([company]),
      "PATCH /companies/c1": () => json({}),
    });
    renderSWR(<CompanyInsights />);
    const input = await screen.findByLabelText("Industry of Stripe");
    await userEvent.type(input, "Fintech{Enter}");
    expect(body(calls(fetch, "PATCH")[0])).toEqual({ industry: "Fintech" });
  });

  it("renders resume and board analytics", async () => {
    routeFetch({
      "GET /insights/resumes": () =>
        json({
          resume_variant: [segment("resume.pdf v2")], tailoring: [segment("tailored by rules")],
          cover_letter: [segment("with a cover letter")], cover_letter_method: [], regenerated: [segment("first version")],
          applied_via: [],
        }),
      "GET /insights/boards": () => json([{ ...segment("greenhouse", { label: "Greenhouse" }), funnel: summary().funnel }]),
    });
    renderSWR(<ResumePerformance />);
    expect(await screen.findByText("resume.pdf v2")).toBeInTheDocument();
    expect(screen.getByText("No submitted applications yet.")).toBeInTheDocument();
    renderSWR(<BoardPerformance />);
    expect(await screen.findByRole("heading", { name: "Greenhouse funnel" })).toBeInTheDocument();
  });

  it("groups the timeline by day", async () => {
    routeFetch({
      "GET /applications/timeline": () =>
        json([
          { at: "2026-11-20T15:00:00Z", kind: "offer", label: "Offer", application_id: "ap1", job_id: "j1", job_title: "Backend Engineer", company_name: "Stripe", status: "completed", detail: { notes: "Verbal" } },
          { at: "2026-11-01T10:00:00Z", kind: "submitted", label: "Application submitted", application_id: "ap1", job_id: "j1", job_title: "Backend Engineer", company_name: "Stripe", status: null, detail: {} },
        ]),
    });
    renderSWR(<OutcomeTimeline />);
    expect(await screen.findByText("Offer")).toBeInTheDocument();
    expect(screen.getByText("Application submitted")).toBeInTheDocument();
    expect(screen.getByText("Verbal")).toBeInTheDocument();
  });
});
