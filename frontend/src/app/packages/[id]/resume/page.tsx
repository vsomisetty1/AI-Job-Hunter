// Tailored resume viewer.
import { TailoredResumeViewer } from "@/components/packages/TailoredResumeViewer";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TailoredResumeViewer id={id} />;
}
