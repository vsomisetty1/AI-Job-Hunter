import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockFetch } from "@/test/factories";

import { ResumeUpload } from "./ResumeUpload";

afterEach(() => vi.unstubAllGlobals());

describe("ResumeUpload", () => {
  it("rejects unsupported files without calling the API", async () => {
    const fetch = mockFetch();
    render(<ResumeUpload />);
    await userEvent.upload(screen.getByLabelText("Resume file"), new File(["x"], "cv.txt", { type: "text/plain" }), {
      applyAccept: false,
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Only PDF and DOCX");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uploads and reports success", async () => {
    mockFetch(json({ resume: { id: "r1", filename: "cv.pdf" }, task_id: "t1" }, 201));
    const onUploaded = vi.fn();
    render(<ResumeUpload onUploaded={onUploaded} />);
    await userEvent.click(screen.getByLabelText(/primary resume/));
    await userEvent.upload(
      screen.getByLabelText("Resume file"),
      new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" }),
    );
    expect(onUploaded).toHaveBeenCalledWith(expect.objectContaining({ task_id: "t1" }));
  });

  it("shows the server's error message", async () => {
    mockFetch(json({ error: { code: "invalid_file", message: "The PDF contains active content." } }, 422));
    render(<ResumeUpload />);
    await userEvent.upload(
      screen.getByLabelText("Resume file"),
      new File(["%PDF-1.4"], "cv.pdf", { type: "application/pdf" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("active content");
  });
});
