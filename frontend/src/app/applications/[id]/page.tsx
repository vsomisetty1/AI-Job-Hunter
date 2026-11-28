// Application review: the filled form, waiting for your decision.
import { ApplicationReview } from "@/components/applications/ApplicationReview";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ApplicationReview id={id} />;
}
