// Resume detail page.
import { ResumeDetailView } from "@/components/resumes/ResumeDetailView";

export default async function ResumePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ResumeDetailView id={id} />;
}
