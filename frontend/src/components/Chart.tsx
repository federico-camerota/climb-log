// SPDX-License-Identifier: GPL-3.0-or-later
// ECharts behind a small wrapper of our own (D-008, D-070): only the parts the dashboard uses
// are registered (a smaller bundle), and the chart follows the light/dark scheme.
import { useComputedColorScheme } from "@mantine/core";
import { BarChart, BoxplotChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use as register, type EChartsCoreOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
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
  CanvasRenderer,
]);

interface Props {
  option: EChartsCoreOption;
  height?: number;
  label: string; // what the chart shows, for screen readers
}

/** One ECharts chart: created on mount (again when the colour scheme changes), its option
 * replaced when it changes, resized with its container. */
export function Chart({ option, height = 320, label }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const dark = useComputedColorScheme("light") === "dark";
  const chart = useRef<ReturnType<typeof init> | null>(null);

  useEffect(() => {
    if (box.current === null) return undefined;
    const created = init(box.current, dark ? "dark" : undefined);
    chart.current = created;
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
