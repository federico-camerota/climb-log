// SPDX-License-Identifier: GPL-3.0-or-later
// ECharts behind a small wrapper of our own (D-008, D-070): only the parts the dashboard uses
// are registered (a smaller bundle), and the chart follows the light/dark scheme. Drawn as SVG,
// not on a canvas (D-097): Firefox's GPU canvas on Linux can leave a drawn chart blank until a
// click repaints it, and our charts are a few hundred points at most.
import { useComputedColorScheme } from "@mantine/core";
import { BarChart, BoxplotChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { init, use as register, type EChartsCoreOption } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

register([
  LineChart,
  HeatmapChart,
  BarChart,
  BoxplotChart,
  ScatterChart,
  CalendarComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  MarkAreaComponent,
  DataZoomComponent,
  VisualMapComponent,
  SVGRenderer,
]);

/** What a click on a chart's item gives: its value (a calendar day: `[date, piece]`). */
export interface ChartClick {
  value: unknown;
}

interface Props {
  option: EChartsCoreOption;
  height?: number;
  label: string; // what the chart shows, for screen readers
  onClick?: (item: ChartClick) => void; // a click on an item (a bar, a calendar day)
}

/** One ECharts chart: created on mount (again when the colour scheme changes), its option
 * replaced when it changes, resized with its container. */
export function Chart({ option, height = 320, label, onClick }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const dark = useComputedColorScheme("light") === "dark";
  const chart = useRef<ReturnType<typeof init> | null>(null);
  const click = useRef(onClick); // the latest handler, without recreating the chart
  useEffect(() => {
    click.current = onClick;
  }, [onClick]);

  useEffect(() => {
    if (box.current === null) return undefined;
    const created = init(box.current, dark ? "dark" : undefined, { renderer: "svg" });
    chart.current = created;
    created.on("click", (item) => {
      click.current?.({ value: (item as { value?: unknown }).value });
    });
    const observer = new ResizeObserver(() => {
      created.resize();
    });
    observer.observe(box.current);
    return () => {
      observer.disconnect();
      created.dispose();
      chart.current = null;
    };
  }, [dark]);

  useEffect(() => {
    // no entry animation: the numbers matter, not the motion (and a screenshot gets them all)
    chart.current?.setOption({ backgroundColor: "transparent", animation: false, ...option }, true);
  }, [option, dark]);

  return <div ref={box} role="img" aria-label={label} style={{ width: "100%", height }} />;
}
