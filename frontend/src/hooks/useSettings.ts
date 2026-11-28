"use client";

// SWR hook for settings, plus a save helper that refreshes the cache.
import useSWR from "swr";

import { settingsApi } from "@/lib/api/settings";
import type { Settings, SettingsUpdate } from "@/types";

export function useSettings() {
  const swr = useSWR<Settings>("settings", settingsApi.get);
  const save = async (patch: SettingsUpdate) => {
    const updated = await settingsApi.update(patch);
    await swr.mutate(updated, { revalidate: false });
    return updated;
  };
  return { ...swr, save };
}
