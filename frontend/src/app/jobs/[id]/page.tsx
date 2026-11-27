// Job detail page.
import { JobDetailView } from "@/components/jobs/JobDetailView";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobDetailView id={id} />;
}
