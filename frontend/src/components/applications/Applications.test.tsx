import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, routeFetch, submission } from "@/test/factories";
import { renderSWR } from "@/test/swr";

import { ApplicationReview } from "./ApplicationReview";
import { ApplicationsQueue } from "./ApplicationsQueue";
import { AutomationLogs } from "./AutomationLogs";
import { SubmissionHistory } from "./SubmissionHistory";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(useRouter().push).mockClear();
});

const calls = (fetch: ReturnType<typeof routeFetch>, method: string) =>
  fetch.mock.calls.filter((c) => ((c[1] as RequestInit | undefined)?.method ?? "GET") === method);

const ready = {
  package_id: "pk2",
  application_id: "ap2",
  job_id: "j2",
  job_title: "Platform Engineer",
  company_name: "Lever Co",
  platform: "lever",
  supported: true,
  job_status: "shortlisted",
  approved_at: "2026-11-27T09:00:00Z",
};

describe("ApplicationsQueue", () => {
  it("lists ready packages, open forms and failures, and starts a run", async () => {
    const failed = submission({
      id: "sb9",
      status: "failed",
      error: "No application form found on the greenhouse page.",
      error_kind: "ats_changed",
      job_title: "Data Engineer",
      failed_at: "2026-11-27T10:05:00Z",
    });
    const fetch = routeFetch({
      "GET /automation/queue": () => json({ ready: [ready], active: [submission()], needs_attention: [failed] }),
      "POST /automation/submissions": () =>
        json({ submission_id: "sb3", task_id: "t1", status: "queued", detail: "Opening" }, 202),
    });
    renderSWR(<ApplicationsQueue />);
    expect(await screen.findByText(/Nothing is sent until you review the form/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Senior Backend Engineer" })).toHaveAttribute("href", "/applications/sb1");
    expect(screen.getByText("1 to fill in")).toBeInTheDocument();
    // Failure recovery inline.
    expect(screen.getByText(/Form layout changed:/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Fill application form" }));
    const post = calls(fetch, "POST")[0];
    expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({ package_id: "pk2" });
    expect(useRouter().push).toHaveBeenCalledWith("/applications/sb3");
  });
});

describe("ApplicationReview", () => {
  it("shows the review checklist and fills a missing field", async () => {
    let current = submission();
    const fetch = routeFetch({
      "GET /automation/submissions/sb1": () => json(current),
      "PATCH /automation/submissions/sb1/fields": () => {
        current = submission({ ready: true, missing_count: 0, review: { ...submission().review, missing: [], ready: true } });
        return json(current);
      },
    });
    renderSWR(<ApplicationReview id="sb1" />);
    expect(await screen.findByText("uploaded: Jordan_Rivera_Resume.pdf")).toBeInTheDocument();
    expect(screen.getByText("uploaded: Jordan_Rivera_Cover_Letter.pdf")).toBeInTheDocument();
    expect(screen.getByText("(voluntary: declined)")).toBeInTheDocument();
    // Consent is listed for the user, never ticked.
    expect(screen.getByText("I agree to the privacy policy")).toBeInTheDocument();
    // Submitting is blocked while a required field is missing.
    expect(screen.getByRole("button", { name: "Submit application…" })).toBeDisabled();

    const missing = screen.getByRole("heading", { name: "Missing fields" }).closest("section") as HTMLElement;
    await userEvent.selectOptions(within(missing).getByRole("combobox"), "Payments");
    await userEvent.click(within(missing).getByRole("button", { name: "Save to form" }));
    const patch = calls(fetch, "PATCH")[0];
    expect(JSON.parse(String((patch[1] as RequestInit).body))).toEqual({ key: "team", value: "Payments" });
    expect(await screen.findByRole("button", { name: "Submit application…" })).toBeEnabled();
  });

  it("submits only after an explicit confirmation", async () => {
    const fetch = routeFetch({
      "GET /automation/submissions/sb1": () =>
        json(submission({ ready: true, review: { ...submission().review, missing: [], ready: true } })),
      "POST /automation/submissions/sb1/submit": () =>
        json({ submission_id: "sb1", task_id: "t2", status: "submitting", detail: "Submitting" }, 202),
    });
    renderSWR(<ApplicationReview id="sb1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Submit application…" }));
    const send = screen.getByRole("button", { name: "Submit to Stripe" });
    expect(send).toBeDisabled();
    expect(calls(fetch, "POST")).toHaveLength(0);
    await userEvent.click(screen.getByRole("checkbox", { name: /I reviewed the filled form/ }));
    await userEvent.click(send);
    const post = calls(fetch, "POST")[0];
    expect(String(post[0])).toContain("/automation/submissions/sb1/submit");
    expect(JSON.parse(String((post[1] as RequestInit).body))).toEqual({ confirm: true });
  });

  it("explains a closed browser session and offers retry", async () => {
    const fetch = routeFetch({
      "GET /automation/submissions/sb1": () => json(submission({ live: false })),
      "POST /automation/submissions/sb1/retry": () =>
        json({ submission_id: "sb1", task_id: "t3", status: "queued", detail: "Reopening" }, 202),
    });
    renderSWR(<ApplicationReview id="sb1" />);
    expect(await screen.findByText(/browser window for this form was closed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry (reopen and refill)" }));
    expect(String(calls(fetch, "POST")[0][0])).toContain("/retry");
  });

  it("guards against applying twice after an unconfirmed submission", async () => {
    const fetch = routeFetch({
      "GET /automation/submissions/sb1": () =>
        json(submission({ status: "failed", error_kind: "unconfirmed", error: "The site did not confirm.", recovery_hint: "Check your email." })),
      "POST /packages/pk1/mark-submitted": () => json({}),
    });
    renderSWR(<ApplicationReview id="sb1" />);
    expect(await screen.findByText(/may have been sent/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry anyway" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "It went through: mark as applied" }));
    expect(String(calls(fetch, "POST")[0][0])).toContain("/packages/pk1/mark-submitted");
  });

  it("shows the confirmation of a submitted application", async () => {
    routeFetch({
      "GET /automation/submissions/sb1": () =>
        json(submission({ status: "submitted", confirmed_at: "2026-11-27T10:01:00Z", submitted_at: "2026-11-27T10:01:05Z", confirmation_text: "Thank you for applying" })),
    });
    renderSWR(<ApplicationReview id="sb1" />);
    expect(await screen.findByText(/“Thank you for applying”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit application…" })).not.toBeInTheDocument();
  });
});

describe("SubmissionHistory and AutomationLogs", () => {
  it("lists runs and filters by status", async () => {
    const fetch = routeFetch({
      "GET /automation/submissions": () =>
        json({ items: [submission({ status: "submitted", confirmed_at: "2026-11-27T10:01:00Z" })], total: 1, limit: 100, offset: 0 }),
    });
    renderSWR(<SubmissionHistory />);
    expect(await screen.findByRole("link", { name: "Senior Backend Engineer" })).toHaveAttribute("href", "/applications/sb1");
    await userEvent.click(screen.getByRole("tab", { name: "Failed" }));
    await vi.waitFor(() => expect(fetch.mock.calls.some((c) => String(c[0]).includes("status=failed"))).toBe(true));
  });

  it("shows log lines for one run", async () => {
    const fetch = routeFetch({
      "GET /automation/logs": () =>
        json({
          items: [
            { id: "l1", submission_id: "sb1", job_title: "Senior Backend Engineer", company_name: "Stripe", level: "warning", step: "review", message: "Waiting for you: 1 missing, 0 problems", detail: {}, created_at: "2026-11-27T10:00:20Z" },
          ],
          total: 1,
          limit: 200,
          offset: 0,
        }),
    });
    renderSWR(<AutomationLogs submissionId="sb1" />);
    expect(await screen.findByText("Waiting for you: 1 missing, 0 problems")).toBeInTheDocument();
    expect(String(fetch.mock.calls[0][0])).toContain("submission_id=sb1");
  });
});
