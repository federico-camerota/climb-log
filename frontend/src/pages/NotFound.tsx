// SPDX-License-Identifier: GPL-3.0-or-later
import { Anchor, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

export function NotFound() {
  return (
    <Stack>
      <Title order={2}>Page not found</Title>
      <Text>
        <Anchor component={Link} to="/">
          Back to Today
        </Anchor>
      </Text>
    </Stack>
  );
}
