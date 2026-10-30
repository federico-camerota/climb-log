// SPDX-License-Identifier: GPL-3.0-or-later
import { Text } from "@mantine/core";

/** What a page will show, and the issue that brings it: "<text> with #<issue>." */
export function Placeholder({ text, issue }: { text: string; issue: number }) {
  return (
    <Text c="dimmed">
      {text} with #{issue}.
    </Text>
  );
}
