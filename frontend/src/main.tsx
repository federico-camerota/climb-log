// SPDX-License-Identifier: GPL-3.0-or-later
import "@mantine/core/styles.css";
import "@mantine/dates/styles.css";
import "./lib/dayjs";

import { MantineProvider } from "@mantine/core";
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { makeQueryClient } from "./api/queries";
import { routes } from "./routes";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}

createRoot(root).render(
  <StrictMode>
    {/* "auto" follows the operating system's light/dark setting until the toggle is used (06-ui). */}
    <MantineProvider defaultColorScheme="auto">
      <QueryClientProvider client={makeQueryClient()}>
        <RouterProvider router={createBrowserRouter(routes)} />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
