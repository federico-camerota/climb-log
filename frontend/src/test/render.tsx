// SPDX-License-Identifier: GPL-3.0-or-later
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { routes } from "../routes";

/** A client per test, without retries (a failure shows at once). */
function testClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

/** Render inside the providers main.tsx sets up, outside the router. */
export function renderWithProviders(ui: ReactElement): RenderResult {
  return render(
    <MantineProvider env="test">
      <QueryClientProvider client={testClient()}>{ui}</QueryClientProvider>
    </MantineProvider>,
  );
}

/** Render the whole app at `path`; the router is returned to check where it went. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const result = render(
    <MantineProvider env="test">
      <QueryClientProvider client={testClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { ...result, router };
}
