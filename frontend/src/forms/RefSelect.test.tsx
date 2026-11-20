// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReferenceTableRows } from "../api/client";
import { stubApi } from "../test/api";
import { renderWithProviders } from "../test/render";
import { FieldInput } from "./FieldInput";

// A fictional reference table (D-113): two exercises in use and one retired.
const ROWS: ReferenceTableRows = {
  module: "mobility",
  table: {
    name: "exercises",
    label: "Exercises",
    tab: "Exercises",
    key: "id",
    display: "name",
    columns: ["id", "name", "retired"],
    week_columns: [],
    per_week_label: null,
  },
  rows: [
    { values: { id: "A1", name: "Wall slides", retired: false }, row: 3 },
    { values: { id: "A2", name: "Band pulls", retired: true }, row: 4 },
    { values: { id: "B1", name: "Hip airplanes", retired: false }, row: 5 },
  ],
  issues: [],
  as_of: null,
  offline: false,
};

function renderRef(value: string, onChange = vi.fn()) {
  stubApi({ "/api/modules/mobility/reference/exercises": ROWS });
  renderWithProviders(
    <FieldInput
      module="mobility"
      name="exercise"
      field={{ type: "ref", reference: "exercises" }}
      value={value}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("a ref field", () => {
  it("offers the rows in use as key · name and stores the key", async () => {
    const onChange = renderRef("");
    await userEvent.click(screen.getByRole("combobox", { name: "Exercise" }));
    expect(
      await screen.findByRole("option", { name: "A1 · Wall slides", hidden: true }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /Band pulls/, hidden: true }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "B1 · Hip airplanes", hidden: true }));
    expect(onChange).toHaveBeenCalledWith("B1");
  });

  it("keeps a retired row the record already has", async () => {
    renderRef("a2");
    expect(await screen.findByDisplayValue("A2 · Band pulls (retired)")).toBeInTheDocument();
  });

  it("shows a key that is no row as it is", async () => {
    renderRef("ZZ");
    expect(await screen.findByDisplayValue("ZZ (not in Exercises)")).toBeInTheDocument();
  });
});
