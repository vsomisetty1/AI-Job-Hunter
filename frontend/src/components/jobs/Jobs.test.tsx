import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { searchQuery } from "@/lib/api/jobs";
import { jobDetail, jobScore, jobSummary, json, routeFetch, scoringSummary } from "@/test/factories";
import { renderSWR } from "@/test/swr";

import { JobDetailView } from "./JobDetailView";
import { JobsPage } from "./JobsPage";
import { ScoreBadge } from "./ScoreBadge";

afterEach(() => vi.unstubAllGlobals());

const page = (items = [jobSummary()], total = items.length) => () =>
  json({ items, total, limit: 50, offset: 0 });

describe("searchQuery", () => {
  it("drops empty values", () => {
    expect(searchQuery({ q: "", source: "lever", include_expired: false, offset: 0, limit: 50 })).toBe(
      "?source=lever&offset=0&limit=50",
    );
    expect(searchQuery({})).toBe("");
  });
});

describe("JobsPage", () => {
  it("lists jobs with salary and links to detail", async () => {
    routeFetch({ "GET /jobs": page() });
    renderSWR(<JobsPage />);
    const link = await screen.findByRole("link", { name: "Senior Backend Engineer" });
    expect(link).toHaveAttribute("href", "/jobs/j1");
    const row = link.closest("tr")!;
    expect(within(row).getByText("$180k – $220k")).toBeInTheDocument();
    expect(screen.getByText("1–1 of 1 jobs")).toBeInTheDocument();
  });

  it("searches and filters through the API", async () => {
    const fetch = routeFetch({ "GET /jobs": page() });
    renderSWR(<JobsPage />);
    await screen.findByText("Senior Backend Engineer");
    await userEvent.type(screen.getByRole("searchbox"), "backend");
    await userEvent.selectOptions(screen.getByLabelText("Workplace"), "remote");
    await vi.waitFor(() => {
      const urls = fetch.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes("q=backend") && u.includes("remote_type=remote"))).toBe(true);
    });
  });

  it("points to discovery when there are no jobs yet", async () => {
    routeFetch({
      "GET /jobs": page([], 0),
      "GET /scoring/summary": () => json(scoringSummary({ jobs_active: 0, jobs_passed: 0 })),
    });
    renderSWR(<JobsPage />);
    expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument();
  });
});

describe("Jobs scoring", () => {
  it("sorts by score and shows matches by default, with a score column", async () => {
    const fetch = routeFetch({
      "GET /jobs": page([
        jobSummary(),
        jobSummary({ id: "j2", title: "PHP Dev", score: null, score_method: null, status: "filtered",
                     filter_reason: "Excluded keyword 'PHP' in the title" }),
      ]),
      "GET /scoring/summary": () => json(scoringSummary()),
    });
    renderSWR(<JobsPage />);
    const row = (await screen.findByRole("link", { name: "Senior Backend Engineer" })).closest("tr")!;
    expect(within(row).getByLabelText("Score 82 by rules")).toHaveTextContent("82");
    expect(screen.getByText("Filtered: Excluded keyword 'PHP' in the title")).toBeInTheDocument();
    expect(screen.getByLabelText("Not scored")).toBeInTheDocument();
    const first = String(fetch.mock.calls.find((c) => String(c[0]).includes("/jobs?"))![0]);
    expect(first).toContain("sort=score");
    expect(first).toContain("filter_state=passed");
    expect(await screen.findByLabelText("Scoring status")).toHaveTextContent("2 match your filters, 1 filtered out");
  });

  it("sends the filter controls to the API", async () => {
    const fetch = routeFetch({ "GET /jobs": page(), "GET /scoring/summary": () => json(scoringSummary()) });
    renderSWR(<JobsPage />);
    await screen.findByText("Senior Backend Engineer");
    await userEvent.selectOptions(screen.getByLabelText("Show"), "rejected");
    await userEvent.selectOptions(screen.getByLabelText("Min score"), "75");
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "newest");
    await vi.waitFor(() => {
      const urls = fetch.mock.calls.map((c) => String(c[0]));
      expect(
        urls.some((u) => u.includes("filter_state=rejected") && u.includes("min_score=75") && u.includes("sort=newest")),
      ).toBe(true);
    });
  });

  it("starts a re-score run", async () => {
    const fetch = routeFetch({
      "GET /jobs": page(),
      "GET /scoring/summary": () => json(scoringSummary()),
      "POST /scoring/runs": () => json({ task_id: "t1", status: "queued", detail: "started" }, 202),
    });
    renderSWR(<JobsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Re-score" }));
    await vi.waitFor(() =>
      expect(fetch.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "POST")).toBe(true),
    );
  });

  it("asks for a resume when there is no profile", async () => {
    routeFetch({ "GET /jobs": page(), "GET /scoring/summary": () => json(scoringSummary({ profile_id: null })) });
    renderSWR(<JobsPage />);
    expect(await screen.findByText(/to get scores/)).toBeInTheDocument();
  });

  it("colours badges by score and marks Claude scores", () => {
    const { rerender } = renderSWR(<ScoreBadge score={91} method="claude" />);
    expect(screen.getByLabelText("Score 91 by Claude")).toHaveClass("bg-emerald-100");
    rerender(<ScoreBadge score={20} method="rules" />);
    expect(screen.getByLabelText("Score 20 by rules")).toHaveClass("bg-red-100");
  });
});

describe("JobDetailView", () => {
  it("explains the score and the filter decision", async () => {
    routeFetch({
      "GET /jobs/j1": () =>
        json(
          jobDetail({
            scores: [
              jobScore(),
              jobScore({
                id: "s2", scoring_method: "claude", overall_score: 64, is_current: false,
                model: "claude-haiku-5-5", input_tokens: 900, output_tokens: 100,
                interview_probability: 40, rationale: "Decent fit.",
                breakdown: { strengths: ["APIs"], concerns: ["No Kubernetes"] },
              }),
            ],
            filter_result: {
              passed: true,
              version: "1",
              checks: [
                { rule: "location", passed: true, reason: "Location matches 'San Francisco'" },
                { rule: "salary", passed: true, reason: "Salary not listed" },
              ],
            },
          }),
        ),
    });
    renderSWR(<JobDetailView id="j1" />);
    expect(await screen.findByText("Rule-based score")).toBeInTheDocument();
    expect(screen.getByText("3 of 4 skills match; missing Kubernetes")).toBeInTheDocument();
    const rulesCard = screen.getByText("Rule-based score").closest("section")!;
    expect(within(rulesCard).getByRole("meter", { name: "Skills" })).toHaveAttribute("aria-valuenow", "78");
    expect(screen.getByText(/Based on 90% of the scoring weight/)).toBeInTheDocument();
    expect(screen.getByText("Claude score")).toBeInTheDocument();
    expect(screen.getByText(/Out of date/)).toBeInTheDocument();
    expect(screen.getByText("No Kubernetes")).toBeInTheDocument();
    // Skills come from the rules score while the Claude one is stale.
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    expect(screen.getByText("kept")).toBeInTheDocument();
    expect(screen.getByText("Location matches 'San Francisco'")).toBeInTheDocument();
  });

  it("says when a job is not scored or filtered yet", async () => {
    routeFetch({ "GET /jobs/j1": () => json(jobDetail({ score: null, score_method: null })) });
    renderSWR(<JobDetailView id="j1" />);
    expect(await screen.findByText(/Not scored\./)).toBeInTheDocument();
    expect(screen.getByText("Not checked against your preferences yet.")).toBeInTheDocument();
  });


  it("renders the description as text and never links unsafe URLs", async () => {
    routeFetch({
      "GET /jobs/j1": () =>
        json(jobDetail({ description: "<img src=x onerror=alert(1)> Build", url: "javascript:alert(1)" })),
    });
    const { container } = renderSWR(<JobDetailView id="j1" />);
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)> Build/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByRole("link", { name: /View posting/ })).toBeNull();
    expect(screen.getByText("5+ years of Python")).toBeInTheDocument();
  });

  it("shows the raw payload on request", async () => {
    const fetch = routeFetch({
      "GET /jobs/j1": () => json(jobDetail()),
      "GET /jobs/j1/raw": () => json({ source: "greenhouse", external_id: "4001", raw: { id: 4001, title: "X" } }),
    });
    renderSWR(<JobDetailView id="j1" />);
    expect(await screen.findByRole("link", { name: /View posting/ })).toHaveAttribute(
      "href",
      "https://acme.example/careers?gh_jid=4001",
    );
    expect(fetch.mock.calls.some((c) => String(c[0]).endsWith("/raw"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Show raw JSON" }));
    expect(await screen.findByLabelText("Raw job payload")).toHaveTextContent('"id": 4001');
  });
});
