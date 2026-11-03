// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../test/render";
import { Chart } from "./Chart";

describe("Chart", () => {
  it("draws SVG, not a canvas (D-097)", () => {
    const option = {
      xAxis: { type: "category", data: ["Mon", "Tue"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: [3, 5] }],
    };
    renderWithProviders(<Chart option={option} label="Sessions" />);
    const box = screen.getByRole("img", { name: "Sessions" });
    expect(box.querySelector("svg")).not.toBeNull();
    expect(box.querySelector("canvas")).toBeNull();
  });
});
