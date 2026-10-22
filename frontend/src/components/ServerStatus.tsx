// SPDX-License-Identifier: GPL-3.0-or-later
import { Badge } from "@mantine/core";
import { useEffect, useState } from "react";

import { getHealth, type Health } from "../api/client";

type State = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "unreachable" };

/** Shows whether the backend answers, and which version is running. */
export function ServerStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getHealth().then(
      (health) => {
        if (!cancelled) setState({ kind: "ok", health });
      },
      () => {
        if (!cancelled) setState({ kind: "unreachable" });
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  switch (state.kind) {
    case "loading":
      return <Badge color="gray">Connecting…</Badge>;
    case "ok":
      return <Badge color="green">Server OK · v{state.health.version}</Badge>;
    case "unreachable":
      return <Badge color="red">Server unreachable</Badge>;
  }
}
