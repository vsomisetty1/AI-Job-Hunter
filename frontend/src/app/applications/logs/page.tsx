// Automation logs (optionally for one run: ?submission=<id>).
import { AutomationLogs } from "@/components/applications/AutomationLogs";

export default async function Page({ searchParams }: { searchParams: Promise<{ submission?: string }> }) {
  const { submission } = await searchParams;
  return <AutomationLogs submissionId={submission} />;
}
