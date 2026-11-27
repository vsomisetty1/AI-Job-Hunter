import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { company, discoveryRun, json, routeFetch } from "@/test/factories";
import { renderSWR } from "@/test/swr";

import { CompaniesCard } from "./CompaniesCard";
import { DiscoveryPage } from "./DiscoveryPage";
import { RunPanel } from "./RunPanel";

afterEach(() => vi.unstubAllGlobals());

const health = () =>
  json(
    ["greenhouse", "lever", "ashby"].map((source) => ({
      source,
      display_name: source[0].toUpperCase() + source.slice(1),
      companies_tracked: 0,
      companies_failing: 0,
      last_success_at: null,
      jobs_active: 0,
      probe: null,
    })),
  );

describe("CompaniesCard", () => {
  it("adds a board and shows the server's error for unknown ones", async () => {
    const fetch = routeFetch({
      "POST /companies": () =>
        json({ error: { code: "validation_error", message: "No Lever job board named 'nope'." } }, 422),
    });
    renderSWR(<CompaniesCard companies={[]} onChanged={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText("Platform"), "lever");
    await userEvent.type(screen.getByLabelText("Board name"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No Lever job board");
    expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({ source: "lever", slug: "nope" });
  });

  it("pauses tracking and only offers removal without jobs", async () => {
    const fetch = routeFetch({ "PATCH /companies/c1": () => json(company({ is_tracked: false })) });
    const onChanged = vi.fn();
    renderSWR(
      <CompaniesCard
        companies={[company({ last_crawl_status: "ok", active_jobs: 3 }), company({ id: "c2", name: "Beta", active_jobs: 0 })]}
        onChanged={onChanged}
      />,
    );
    expect(screen.queryByRole("button", { name: "Remove Acme Robotics" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove Beta" })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Pause" })[0]);
    expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual({ is_tracked: false });
    expect(onChanged).toHaveBeenCalled();
  });
});

describe("RunPanel", () => {
  it("starts a run, follows it and refreshes when it ends", async () => {
    let polls = 0;
    routeFetch({
      "POST /discovery/runs": () => json({ run_id: "r1", task_id: "t1", status: "queued", detail: "" }, 202),
      "GET /discovery/runs/r1": () =>
        json(polls++ === 0 ? discoveryRun({ status: "running", finished_at: null, duration_ms: null }) : discoveryRun()),
    });
    const onFinished = vi.fn();
    renderSWR(<RunPanel trackedCount={2} latestId={null} onFinished={onFinished} />);
    await userEvent.click(screen.getByRole("button", { name: "Discover jobs now" }));
    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(await screen.findByText("succeeded", {}, { timeout: 4000 })).toBeInTheDocument();
    await vi.waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
  });

  it("is disabled until a company is tracked", () => {
    renderSWR(<RunPanel trackedCount={0} latestId={null} onFinished={() => {}} />);
    expect(screen.getByRole("button", { name: "Discover jobs now" })).toBeDisabled();
  });
});

describe("DiscoveryPage", () => {
  it("shows companies, suggestions, history and connector health", async () => {
    routeFetch({
      "GET /companies": () => json([company({ last_crawl_status: "ok", active_jobs: 3 })]),
      "GET /companies/directory": () =>
        json([{ source: "ashby", slug: "ramp", name: "Ramp", added: false }]),
      "GET /discovery/runs?limit=20": () => json({ items: [discoveryRun()], total: 1, limit: 20, offset: 0 }),
      "GET /discovery/runs/r1": () => json(discoveryRun()),
      "GET /discovery/health": health,
    });
    renderSWR(<DiscoveryPage />);
    expect(await screen.findByText("Tracked companies (1)")).toBeInTheDocument();
    expect(await screen.findByLabelText(/Ramp/)).toBeInTheDocument();
    expect(await screen.findAllByText("0 tracked · 0 active jobs")).toHaveLength(3);
    expect(await screen.findByText("4 / 3 / 0 / 1")).toBeInTheDocument();
  });
});
