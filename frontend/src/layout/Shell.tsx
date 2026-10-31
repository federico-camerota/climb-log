// SPDX-License-Identifier: GPL-3.0-or-later
import {
  ActionIcon,
  AppShell,
  Burger,
  Group,
  NavLink,
  Title,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Link, Outlet, useLocation } from "react-router";

import { ServerStatus } from "../components/ServerStatus";
import { PAGES } from "./pages";

function isActive(page: string, pathname: string): boolean {
  return page === "/" ? pathname === "/" : pathname === page || pathname.startsWith(`${page}/`);
}

function ColourToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const dark = useComputedColorScheme("light") === "dark";
  return (
    <ActionIcon
      variant="default"
      aria-label={dark ? "Light theme" : "Dark theme"}
      onClick={() => {
        setColorScheme(dark ? "light" : "dark");
      }}
    >
      {dark ? "☀" : "☾"}
    </ActionIcon>
  );
}

/** Desktop-first layout: header and a sidebar, collapsed behind a burger on narrow windows. */
export function Shell() {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();
  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 200, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Title order={3}>climb-log</Title>
          </Group>
          <Group>
            <ServerStatus />
            <ColourToggle />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {PAGES.map((page) => (
          <NavLink
            key={page.path}
            component={Link}
            to={page.path}
            label={page.label}
            active={isActive(page.path, pathname)}
            onClick={close}
          />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
