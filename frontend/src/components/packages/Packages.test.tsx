import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, jobDetail, packageDetail, routeFetch } from "@/test/factories";
import { renderSWR } from "@/test/swr";

import { JobDetailView } from "@/components/jobs/JobDetailView";

import { AnswersViewer } from "./AnswersViewer";
import { CoverLetterViewer } from "./CoverLetterViewer";
import { PackageQueue } from "./PackageQueue";
import { PackageReview } from "./PackageReview";
import { ResumeDiffViewer } from "./ResumeDiffViewer";
import { TailoredResumeViewer } from "./TailoredResumeViewer";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(useRouter().push).mockClear();
});

const calls = (fetch: ReturnType<typeof routeFetch>, method: string) =>
  fetch.mock.calls.filter((c) => ((c[1] as RequestInit | undefined)?.method ?? "GET") === method);

const page = (items: unknown[]) => () => json({ items, total: items.length, limit: 50, offset: 0 });

describe("PackageQueue", () => {
  it("shows packages needing review and switches queues", async () => {
    const fetch = routeFetch({ "GET /packages": page([packageDetail()]) });
    renderSWR(<PackageQueue />);
    const link = await screen.findByRole("link", { name: "Senior Backend Engineer" });
    expect(link).toHaveAttribute("href", "/packages/pk1");
    expect(screen.getByText("1 answer")).toBeInTheDocument();
    const first = String(fetch.mock.calls[0][0]);
    expect(first).toContain("status=generating&status=generated&status=reviewed");
    await userEvent.click(screen.getByRole("tab", { name: "Approved" }));
    await vi.waitFor(() =>
      expect(fetch.mock.calls.some((c) => String(c[0]).includes("status=approved"))).toBe(true),
    );
  });

  it("explains an empty review queue", async () => {
    routeFetch({ "GET /packages": page([]) });
    renderSWR(<PackageQueue />);
    expect(await screen.findByText(/Nothing to review/)).toBeInTheDocument();
  });
});

describe("PackageReview", () => {
  it("summarises the package and marks a new one as reviewed", async () => {
    const fetch = routeFetch({
      "GET /packages/pk1": () => json(packageDetail({ status: "generated" })),
      "POST /packages/pk1/review": () => json(packageDetail({ status: "reviewed" })),
    });
    renderSWR(<PackageReview id="pk1" />);
    expect(await screen.findByText("Tailored by reordering: 2 changes.")).toBeInTheDocument();
    expect(screen.getByText("missing: Kubernetes")).toBeInTheDocument();
    expect(screen.getByText(/182 words/)).toBeInTheDocument();
    expect(screen.getByText(/1 need your input: Why do you want to work at Stripe\?/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Resume (PDF)" })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/v1/packages/pk1/files/resume.pdf",
    );
    await vi.waitFor(() => expect(calls(fetch, "POST").length).toBe(1));
    expect(String(calls(fetch, "POST")[0][0])).toContain("/packages/pk1/review");
  });

  it("approves with notes", async () => {
    const fetch = routeFetch({
      "GET /packages/pk1": () => json(packageDetail()),
      "POST /packages/pk1/approve": () => json(packageDetail({ status: "approved", approved_at: "2026-11-27T11:00:00Z" })),
    });
    renderSWR(<PackageReview id="pk1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await userEvent.type(screen.getByLabelText("Notes (optional)"), "Ready to go");
    await userEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    await vi.waitFor(() => expect(calls(fetch, "POST").length).toBe(1));
    expect(JSON.parse(String((calls(fetch, "POST")[0][1] as RequestInit).body))).toEqual({ notes: "Ready to go" });
    expect(await screen.findByRole("button", { name: "I applied with this package" })).toBeInTheDocument();
  });

  it("needs a reason to reject and shows API errors", async () => {
    routeFetch({
      "GET /packages/pk1": () => json(packageDetail()),
      "POST /packages/pk1/reject": () => json({ error: { code: "conflict", message: "Too late" } }, 409),
    });
    renderSWR(<PackageReview id="pk1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Confirm rejection" });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Why reject it?"), "Letter too generic");
    await userEvent.click(confirm);
    expect(await screen.findByRole("alert")).toHaveTextContent("Too late");
  });

  it("regenerates and opens the new version", async () => {
    const fetch = routeFetch({
      "GET /packages/pk1": () => json(packageDetail()),
      "POST /packages/pk1/regenerate": () =>
        json({ package_id: "pk2", task_id: "t", status: "queued", detail: "x" }, 202),
    });
    renderSWR(<PackageReview id="pk1" />);
    await userEvent.click(await screen.findByLabelText(/Reword with Claude/));
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await vi.waitFor(() => expect(useRouter().push).toHaveBeenCalledWith("/packages/pk2"));
    expect(JSON.parse(String((calls(fetch, "POST")[0][1] as RequestInit).body))).toEqual({
      use_llm: true,
      include_cover_letter: true,
    });
  });

  it("shows generating and failed states", async () => {
    routeFetch({ "GET /packages/pk1": () => json(packageDetail({ status: "failed", error: "Upload a resume first." })) });
    renderSWR(<PackageReview id="pk1" />);
    expect(await screen.findByText("Generation failed: Upload a resume first.")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Package sections" })).toBeNull();
  });
});

describe("package viewers", () => {
  it("shows the tailored resume", async () => {
    routeFetch({ "GET /packages/pk1": () => json(packageDetail()) });
    renderSWR(<TailoredResumeViewer id="pk1" />);
    expect(await screen.findByText("Tailored resume (version 2)")).toBeInTheDocument();
    expect(screen.getByText("Led migration")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tailored resume" })).toHaveAttribute("aria-current", "page");
  });

  it("lists every change with its reason, before and after", async () => {
    routeFetch({ "GET /packages/pk1": () => json(packageDetail()) });
    renderSWR(<ResumeDiffViewer id="pk1" />);
    expect(await screen.findByText("2 changes from your resume")).toBeInTheDocument();
    expect(screen.getByText("Why: Moved the skills this job asks for to the front: Python")).toBeInTheDocument();
    expect(screen.getByLabelText("Before")).toHaveTextContent("Backend engineer.");
    expect(screen.getByLabelText("After")).toHaveTextContent("Senior Backend Engineer with 5+ years");
    const lists = screen.getAllByRole("list").filter((l) => l.tagName === "OL");
    expect(within(lists[1]).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Python", "Go"]);
  });

  it("shows the cover letter as text with its notes", async () => {
    routeFetch({
      "GET /packages/pk1": () =>
        json(packageDetail({ cover_letter: { ...packageDetail().cover_letter!, content: "<b>Dear</b> team" } })),
    });
    const { container } = renderSWR(<CoverLetterViewer id="pk1" />);
    expect(await screen.findByLabelText("Cover letter text")).toHaveTextContent("<b>Dear</b> team");
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/make it personal/)).toBeInTheDocument();
  });

  it("puts answers needing input first and saves edits", async () => {
    const fetch = routeFetch({
      "GET /packages/pk1": () => json(packageDetail()),
      "PATCH /packages/pk1/answers/a2": () => json({ ...packageDetail().answers[1], answer: "Mine", source: "user" }),
    });
    renderSWR(<AnswersViewer id="pk1" />);
    const why = (await screen.findByText("Why do you want to work at Stripe?")).closest("li")!;
    const sponsorship = screen.getByText("Will you now or in the future require visa sponsorship?").closest("li")!;
    // Answers that need input come first.
    expect(why.compareDocumentPosition(sponsorship) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(why).getByText("needs your input")).toBeInTheDocument();
    expect(within(sponsorship).getByText("from your settings")).toBeInTheDocument();
    await userEvent.click(within(why).getByRole("button", { name: "Edit" }));
    const box = screen.getByLabelText("Answer to Why do you want to work at Stripe?");
    await userEvent.clear(box);
    await userEvent.type(box, "I use Stripe every day.");
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await vi.waitFor(() => expect(calls(fetch, "PATCH").length).toBe(1));
    expect(JSON.parse(String((calls(fetch, "PATCH")[0][1] as RequestInit).body))).toEqual({
      answer: "I use Stripe every day.",
    });
  });

  it("does not offer edits once approved", async () => {
    routeFetch({ "GET /packages/pk1": () => json(packageDetail({ status: "approved", approved_at: "2026-11-27T11:00:00Z" })) });
    renderSWR(<AnswersViewer id="pk1" />);
    await screen.findByText("Why do you want to work at Stripe?");
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});

describe("GeneratePackage on the job page", () => {
  it("generates a package and opens it", async () => {
    const fetch = routeFetch({
      "GET /jobs/j1": () => json(jobDetail()),
      "GET /packages": page([]),
      "POST /packages": () => json({ package_id: "pk9", task_id: "t", status: "queued", detail: "x" }, 202),
    });
    renderSWR(<JobDetailView id="j1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate package" }));
    await vi.waitFor(() => expect(useRouter().push).toHaveBeenCalledWith("/packages/pk9"));
    expect(JSON.parse(String((calls(fetch, "POST")[0][1] as RequestInit).body))).toEqual({
      job_id: "j1",
      use_llm: false,
      include_cover_letter: true,
    });
  });

  it("links to the existing package", async () => {
    routeFetch({ "GET /jobs/j1": () => json(jobDetail()), "GET /packages": page([packageDetail()]) });
    renderSWR(<JobDetailView id="j1" />);
    expect(await screen.findByRole("link", { name: "Open package" })).toHaveAttribute("href", "/packages/pk1");
  });
});
