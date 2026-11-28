// Resume diff viewer.
import { ResumeDiffViewer } from "@/components/packages/ResumeDiffViewer";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ResumeDiffViewer id={id} />;
}
