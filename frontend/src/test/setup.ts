// SPDX-License-Identifier: GPL-3.0-or-later
import "@testing-library/jest-dom/vitest";
import "../lib/dayjs";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no matchMedia; Mantine uses it for the colour scheme.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

// Nor ResizeObserver and scrollIntoView, which Mantine's layout and dropdowns use.
class ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = ResizeObserver;
Element.prototype.scrollIntoView = () => undefined;
// Nor document.fonts, which an autosizing Textarea listens to.
Object.defineProperty(document, "fonts", {
  value: { addEventListener: () => undefined, removeEventListener: () => undefined },
});

// findBy… waits 1 s by default: a page's first render (Mantine, a whole form) can take longer
// when the full suite runs in parallel on a busy machine. 3 s stays under vitest's 5 s per test.
configure({ asyncUtilTimeout: 3000 });

afterEach(() => {
  cleanup();
  localStorage.clear(); // the theme and the sidebar's state
  vi.unstubAllGlobals();
});
