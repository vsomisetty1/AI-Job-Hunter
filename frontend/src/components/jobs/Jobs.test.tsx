import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { searchQuery } from "@/lib/api/jobs";
import { jobDetail, jobSummary, json, routeFetch } from "@/test/factories";
import { renderSWR } from "@/test/swr";

import { JobDetailView } from "./JobDetailView";
import { JobsPage } from "./JobsPage";

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
    routeFetch({ "GET /jobs": page([], 0) });
    renderSWR(<JobsPage />);
    expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument();
  });
});

describe("JobDetailView", () => {
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
