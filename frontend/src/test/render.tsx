// SPDX-License-Identifier: GPL-3.0-or-later
import { MantineProvider } from "@mantine/core";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";

/** Render inside MantineProvider, as main.tsx does. */
export function renderWithMantine(ui: ReactElement): RenderResult {
  return render(<MantineProvider>{ui}</MantineProvider>);
}
