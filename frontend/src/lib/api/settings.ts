// Settings API: the user's job-search preferences (single row).
import type { Settings, SettingsUpdate } from "@/types";

import { apiFetch } from "./client";

export const settingsApi = {
  get: () => apiFetch<Settings>("/settings"),
  update: (patch: SettingsUpdate) =>
    apiFetch<Settings>("/settings", { method: "PATCH", body: JSON.stringify(patch) }),
};
