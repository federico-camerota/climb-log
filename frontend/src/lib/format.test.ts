// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, it } from "vitest";

import { formatDateTime } from "./format";

it("shows dates day first", () => {
  expect(formatDateTime("2026-10-30T09:05:00")).toBe("30/10/2026 09:05");
  expect(formatDateTime("2026-10-30")).toBe("30/10/2026");
  expect(formatDateTime("yesterday")).toBe("yesterday");
});
