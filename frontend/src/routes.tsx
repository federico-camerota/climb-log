// SPDX-License-Identifier: GPL-3.0-or-later
import type { RouteObject } from "react-router";

import { Shell } from "./layout/Shell";
import { Dashboards } from "./pages/Dashboards";
import { Log } from "./pages/Log";
import { NotFound } from "./pages/NotFound";
import { Records } from "./pages/Records";
import { Settings } from "./pages/Settings";
import { Today } from "./pages/Today";

/** The app's pages (D-073); FastAPI serves index.html for all of them (D-039). */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Today /> },
      { path: "log/:module?/:form?", element: <Log /> },
      { path: "records/:module?/:entity?", element: <Records /> },
      { path: "dashboards/:module?", element: <Dashboards /> },
      { path: "settings", element: <Settings /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
