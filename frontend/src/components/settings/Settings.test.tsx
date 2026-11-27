import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import { json, routeFetch, settings } from "@/test/factories";
import { renderSWR } from "@/test/swr";

import { SettingsForm, settingsPatch } from "./SettingsForm";

afterEach(() => vi.unstubAllGlobals());

describe("settingsPatch", () => {
  it("sends only changed fields, normalised", () => {
    const saved = settings();
    const patch = settingsPatch(saved, {
      locations: "San Francisco, NYC, nyc",
      remote: "any",
      jobTypes: [],
      salaryMin: "150000",
      salaryTarget: "",
      currency: "usd",
      sponsorship: true,
      workAuthorization: "",
      visaStatus: " ",
      companies: "Acme\n\n Globex ",
      keywords: "",
      claudeEnabled: false,
      claudeMinScore: "60",
    });
    expect(patch).toEqual({
      preferred_locations: ["San Francisco", "NYC"],
      salary_min: 150000,
      requires_sponsorship: true,
      excluded_companies: ["Acme", "Globex"],
    });
  });
});

describe("SettingsForm", () => {
  it("saves filtering and scoring preferences", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderSWR(<SettingsForm settings={settings()} onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText("Workplace"), "remote_only");
    await userEvent.click(screen.getByLabelText("Contract"));
    await userEvent.type(screen.getByLabelText(/^Excluded keywords/), "PHP, clearance");
    await userEvent.click(screen.getByLabelText("I need visa sponsorship"));
    await userEvent.click(screen.getByLabelText("Also score my best matches with Claude"));
    const minScore = screen.getByLabelText("Only jobs with a rule score of at least");
    await userEvent.clear(minScore);
    await userEvent.type(minScore, "75");
    await userEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(onSave).toHaveBeenCalledWith({
      remote_preference: "remote_only",
      job_types: ["contract"],
      requires_sponsorship: true,
      excluded_keywords: ["PHP", "clearance"],
      claude_scoring_enabled: true,
      claude_scoring_min_score: 75,
    });
    expect(await screen.findByText(/Saved. Jobs are being filtered and scored again./)).toBeInTheDocument();
  });

  it("blocks a minimum above the target and reports no-op saves", async () => {
    const onSave = vi.fn();
    renderSWR(<SettingsForm settings={settings()} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(screen.getByText("Nothing changed.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Minimum (yearly)"), "200000");
    await userEvent.type(screen.getByLabelText("Target (yearly)"), "150000");
    expect(screen.getByRole("alert")).toHaveTextContent("cannot be above the target");
    expect(screen.getByRole("button", { name: "Save preferences" })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows API errors", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("salary_min must be <= salary_target"));
    renderSWR(<SettingsForm settings={settings()} onSave={onSave} />);
    await userEvent.type(screen.getByLabelText("Minimum (yearly)"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("salary_min must be <= salary_target");
  });
});

describe("SettingsPage", () => {
  it("loads settings and PATCHes changes", async () => {
    const fetch = routeFetch({
      "GET /settings": () => json(settings()),
      "PATCH /settings": () => json(settings({ excluded_companies: ["Initech"] })),
    });
    renderSWR(<SettingsPage />);
    await userEvent.type(await screen.findByLabelText(/^Excluded companies/), "Initech");
    await userEvent.click(screen.getByRole("button", { name: "Save preferences" }));
    await vi.waitFor(() => {
      const patch = fetch.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "PATCH");
      expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({ excluded_companies: ["Initech"] });
    });
  });
});
