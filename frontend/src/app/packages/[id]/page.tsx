// Package review.
import { PackageReview } from "@/components/packages/PackageReview";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PackageReview id={id} />;
}
