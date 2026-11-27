// Cover letter viewer.
import { CoverLetterViewer } from "@/components/packages/CoverLetterViewer";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CoverLetterViewer id={id} />;
}
