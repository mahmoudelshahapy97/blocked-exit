import { useMemo } from "react";
import { useTheme } from "@mui/material/styles";

/**
 * Chart colors and Chart.js defaults, by role.
 *
 * Categorical series take slots in fixed order (never cycled, never by rank),
 * so "Incidents" is the same blue on every chart. Each mode is its own set of
 * steps, validated against this app's card surface with the dataviz
 * validator (adjacent and all-pairs CVD ΔE >= 9, normal-vision >= 20):
 *   light, #ffffff: blue/orange/aqua — aqua is 2.8:1, so every chart that
 *                   uses it also has a table view (the relief rule)
 *   dark,  #131c2e: all three >= 3:1
 * Only three slots validate all-pairs; no chart here needs more.
 */
const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a"],
  dark: ["#3987e5", "#d95926", "#199e70"],
};

// One-hue blue ramp, step 100 -> 700. Near zero recedes toward the surface:
// pale on light, deep on dark.
const BLUE_RAMP = [
  "#cde2fb",
  "#9ec5f4",
  "#6da7ec",
  "#3987e5",
  "#2a78d6",
  "#256abf",
  "#1c5cab",
  "#104281",
  "#0d366b",
];

export function useChartTheme() {
  const theme = useTheme();
  return useMemo(() => {
    const dark = theme.palette.mode === "dark";
    const series = SERIES[dark ? "dark" : "light"];
    const ramp = dark ? [...BLUE_RAMP].reverse() : BLUE_RAMP;
    const text = theme.palette.text.secondary;
    const grid = theme.palette.divider;
    const surface = theme.palette.background.paper;

    /** 0..1 -> a ramp step (the scale is quantized: steps read, gradients don't). */
    const sequential = (fraction) =>
      ramp[Math.min(ramp.length - 1, Math.max(0, Math.round(fraction * (ramp.length - 1))))];

    /** Bars: <= 24px, 4px rounded data end, square at the baseline. */
    const bar = (color) => ({
      backgroundColor: color,
      hoverBackgroundColor: color,
      borderRadius: 4,
      borderSkipped: "start",
      maxBarThickness: 24,
      // Leaves the 2px-or-more surface gap between bars of one group.
      barPercentage: 0.82,
      categoryPercentage: 0.8,
      // The 2px surface gap between touching bars, not a stroke around them.
      borderWidth: 0,
    });

    const line = (color) => ({
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2,
      borderCapStyle: "round",
      borderJoinStyle: "round",
      // Straight segments: smoothing overshoots between counts (dips below 0).
      tension: 0,
      pointRadius: 0,
      pointHoverRadius: 5,
      pointHoverBorderWidth: 2,
      pointHoverBorderColor: surface,
    });

    const axis = (extra = {}) => ({
      ticks: { color: text, font: { size: 11 } },
      grid: { color: grid, lineWidth: 1, drawTicks: false },
      border: { display: false },
      ...extra,
    });

    /** Base options; `legend` only for >= 2 series. */
    const options = ({ legend = false, horizontal = false, xTitle, yTitle } = {}) => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      indexAxis: horizontal ? "y" : "x",
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: 4, right: 8 } },
      plugins: {
        legend: legend
          ? {
              position: "top",
              align: "start",
              labels: { color: text, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 2 },
            }
          : { display: false },
        tooltip: {
          backgroundColor: theme.palette.background.default,
          titleColor: theme.palette.text.primary,
          bodyColor: theme.palette.text.primary,
          borderColor: grid,
          borderWidth: 1,
          padding: 10,
          boxPadding: 4,
          usePointStyle: true,
        },
      },
      scales: {
        x: axis({
          beginAtZero: true,
          grid: { display: horizontal, color: grid, lineWidth: 1, drawTicks: false },
          title: xTitle ? { display: true, text: xTitle, color: text } : undefined,
        }),
        y: axis({
          beginAtZero: true,
          grid: { display: !horizontal, color: grid, lineWidth: 1, drawTicks: false },
          title: yTitle ? { display: true, text: yTitle, color: text } : undefined,
        }),
      },
    });

    return { series, ramp, sequential, bar, line, options, surface, grid, text };
  }, [theme]);
}

export default useChartTheme;
