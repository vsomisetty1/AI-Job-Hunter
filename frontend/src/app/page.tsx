// Dashboard
// PLACEHOLDER - full dashboard implemented in PHASE 8.
import Link from "next/link";

import { Header } from "@/components/layout/Header";
import { Card } from "@/components/ui/Card";

export default function DashboardPage() {
  return (
    <>
      <Header title="Dashboard" />
      <Card>
        <p className="text-sm">
          Start by uploading your <Link href="/resumes" className="text-indigo-600 hover:underline">resume</Link>; your{" "}
          <Link href="/profile" className="text-indigo-600 hover:underline">profile</Link> is generated from it.
        </p>
      </Card>
    </>
  );
}
