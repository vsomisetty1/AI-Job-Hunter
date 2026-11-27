"use client";

// SWR hooks for application packages. A package being generated is polled.
import useSWR from "swr";

import { packagesApi } from "@/lib/api/packages";
import type { Page, PackageDetail, PackageStatus, PackageSummary } from "@/types";

export function usePackages(status: PackageStatus[], jobId?: string) {
  return useSWR<Page<PackageSummary>>(["packages", status.join(","), jobId ?? ""], () =>
    packagesApi.list({ status, jobId }),
    { refreshInterval: (page) => (page?.items.some((p) => p.status === "generating") ? 2000 : 0) },
  );
}

export function usePackage(id: string | null) {
  return useSWR<PackageDetail>(id ? ["package", id] : null, () => packagesApi.get(id as string), {
    refreshInterval: (p) => (p?.status === "generating" ? 1500 : 0),
  });
}
