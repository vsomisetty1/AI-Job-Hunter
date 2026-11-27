// Render with a fresh SWR cache so tests never share data.
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { SWRConfig } from "swr";

export function renderSWR(ui: ReactElement) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>,
  );
}
