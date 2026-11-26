"use client";

// Profile page: status, regenerate, view and edit.
import Link from "next/link";
import { useState } from "react";

import { Header } from "@/components/layout/Header";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useProfile } from "@/hooks/useResumes";
import { errorMessage } from "@/lib/api/client";
import { profileApi } from "@/lib/api/resumes";
import { formatDateTime } from "@/lib/format";

import { ProfileEditor } from "./ProfileEditor";
import { ProfileView } from "./ProfileView";

export function ProfilePage() {
  const { data: profile, error, isLoading, mutate } = useProfile();
  const [editing, setEditing] = useState(false);
  const [keepEdits, setKeepEdits] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  if (isLoading) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  if (!profile) {
    return (
      <>
        <Header title="Profile" />
        <Card>
          <p className="text-sm">
            No profile yet. <Link href="/resumes" className="text-indigo-600 hover:underline">Upload a resume</Link>{" "}
            and your profile is built from it automatically.
          </p>
        </Card>
      </>
    );
  }

  const working = profile.inference_status === "pending" || profile.inference_status === "running";

  async function regenerate() {
    setActionError(null);
    try {
      await profileApi.regenerate({ keep_overrides: keepEdits });
      await mutate();
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  return (
    <>
      <Header
        title="Profile"
        description={profile.inferred_at ? `Generated ${formatDateTime(profile.inferred_at)}` : undefined}
        actions={
          !editing && (
            <>
              <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>
              <Button onClick={() => void regenerate()} disabled={working}>
                {working ? "Generating…" : "Regenerate"}
              </Button>
            </>
          )
        }
      />
      <div className="mb-4 space-y-2">
        {!editing && profile.overrides.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={keepEdits} onChange={(e) => setKeepEdits(e.target.checked)} />
            Keep my edits when regenerating ({profile.overrides.join(", ")})
          </label>
        )}
        {working && <Alert>Building your profile from your primary resume…</Alert>}
        {profile.inference_status === "failed" && (
          <Alert tone="error">Profile generation failed: {profile.inference_error}</Alert>
        )}
        {profile.inference_status === "complete" && profile.warnings.length > 0 && (
          <Alert tone="warning">{profile.warnings.join(" ")}</Alert>
        )}
        {actionError && <Alert tone="error">{actionError}</Alert>}
      </div>
      {editing ? (
        <Card title="Edit profile">
          <ProfileEditor
            profile={profile}
            onCancel={() => setEditing(false)}
            onSaved={(p) => {
              setEditing(false);
              void mutate(p, { revalidate: false });
            }}
          />
        </Card>
      ) : (
        <ProfileView profile={profile} />
      )}
    </>
  );
}
