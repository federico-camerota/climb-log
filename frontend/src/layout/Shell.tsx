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
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
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

/** Desktop-first layout: header and a sidebar with a burger each for narrow and wide windows.
 * On a narrow window the sidebar covers the page, so a link closes it; on a wide one it stays
 * as left, and whether it is open is remembered across reloads (D-074). */
export function Shell() {
  const [mobileOpened, { toggle: toggleMobile, close: closeMobile }] = useDisclosure();
  const [desktopOpened, setDesktopOpened] = useLocalStorage({
    key: "climblog-sidebar",
    defaultValue: true,
    getInitialValueInEffect: false, // read before the first paint: no flash of the sidebar
  });
  const { pathname } = useLocation();
  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 200,
        breakpoint: "sm",
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger
              opened={mobileOpened}
              onClick={toggleMobile}
              hiddenFrom="sm"
              size="sm"
              aria-label="Menu"
              aria-expanded={mobileOpened}
            />
            <Burger
              opened={desktopOpened}
              onClick={() => {
                setDesktopOpened(!desktopOpened);
              }}
              visibleFrom="sm"
              size="sm"
              aria-label="Sidebar"
              aria-expanded={desktopOpened}
            />
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
            onClick={closeMobile}
          />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
