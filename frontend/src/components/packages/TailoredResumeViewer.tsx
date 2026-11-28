"use client";

// The tailored resume as it will be sent.
import { ParsedResumeView } from "@/components/resumes/ParsedResumeView";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";

import { Downloads } from "./Downloads";
import { PackageShell } from "./PackageShell";

export function TailoredResumeViewer({ id }: { id: string }) {
  return (
    <PackageShell id={id} tab="resume">
      {(pkg) =>
        pkg.tailored_resume ? (
          <Card
            title={`Tailored resume (version ${pkg.tailored_resume.version_number})`}
            actions={<Downloads id={pkg.id} doc="resume" label="Download" />}
          >
            {(pkg.tailored_resume.tailoring.rejected_rewrites ?? []).length > 0 && (
              <div className="mb-4">
                <Alert tone="warning">
                  Some suggested rewording was dropped because it added skills or numbers your resume does not
                  have.
                </Alert>
              </div>
            )}
            <ParsedResumeView data={pkg.tailored_resume.content} />
          </Card>
        ) : (
          <Alert tone="warning">This package has no tailored resume.</Alert>
        )
      }
    </PackageShell>
  );
}
