// Discovered jobs: search, filter, paginate. Filters can come from the URL
// (?q=&min_score=), which needs a Suspense boundary for useSearchParams.
import { Suspense } from "react";

import { JobsPage } from "@/components/jobs/JobsPage";

export default function Page() {
  return (
    <Suspense>
      <JobsPage />
    </Suspense>
  );
}
