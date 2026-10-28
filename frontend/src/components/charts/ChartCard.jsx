import { useState } from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import BarChartIcon from "@mui/icons-material/BarChart";
import TableRowsIcon from "@mui/icons-material/TableRows";

import { EmptyState, ErrorState, Loading } from "../DataStates";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

/**
 * One chart with its table-view twin. Every value a chart shows is also in
 * the table, so nothing is readable by hover or by color alone.
 *
 * On refetch the previous render stays, dimmed, instead of flashing a
 * skeleton — filters change often and the layout must not jump.
 */
export default function ChartCard({
  title,
  subtitle,
  loading,
  error,
  onRetry,
  empty,
  emptyText = i18n.t("chartCard.noEvents"),
  height = 300,
  chart,
  table,
  actions,
}) {
  const { t } = useTranslation();
  const [view, setView] = useState("chart");
  const firstLoad = loading && empty === undefined;

  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Stack direction="row" alignItems="flex-start" spacing={1} sx={{ mb: 1.5 }}>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              {title}
            </Typography>
            {subtitle && (
              <Typography variant="caption" color="text.secondary">
                {subtitle}
              </Typography>
            )}
          </Box>
          {actions}
          {chart && table && (
            <ToggleButtonGroup
              size="small"
              exclusive
              value={view}
              onChange={(_, next) => next && setView(next)}
              aria-label={t("chartCard.titleChartOrTable", { title })}
            >
              <ToggleButton value="chart" aria-label={t("chartCard.chartView")}>
                <BarChartIcon fontSize="small" />
              </ToggleButton>
              <ToggleButton value="table" aria-label={t("chartCard.tableView")}>
                <TableRowsIcon fontSize="small" />
              </ToggleButton>
            </ToggleButtonGroup>
          )}
        </Stack>

        {error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : firstLoad ? (
          <Loading label={t("chartCard.aggregating")} height={height} />
        ) : empty ? (
          <EmptyState title={t("chartCard.nothingToShow")} description={emptyText} />
        ) : (
          <Box sx={{ opacity: loading ? 0.5 : 1, transition: "opacity 150ms" }}>
            {view === "chart" && chart ? <Box sx={{ height }}>{chart}</Box> : table}
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
