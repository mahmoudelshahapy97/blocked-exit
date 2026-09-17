import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Grid from "@mui/material/Grid2";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import EventNoteIcon from "@mui/icons-material/EventNote";
import TimerIcon from "@mui/icons-material/Timer";
import DoorFrontIcon from "@mui/icons-material/DoorFront";
import NotificationsIcon from "@mui/icons-material/NotificationsActive";

import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip as ChartTooltip,
} from "chart.js";
import { Bar } from "react-chartjs-2";

import { analytics } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { formatDuration, formatNumber, formatPct } from "../utils/format";

ChartJS.register(CategoryScale, LinearScale, BarElement, ChartTooltip, Legend);

const WINDOWS = [
  { value: 1, label: "Last 24 hours" },
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 90, label: "Last 90 days" },
];

export default function Analytics() {
  const theme = useTheme();
  const [days, setDays] = useState(7);

  const {
    data: summary,
    error: summaryError,
    loading: summaryLoading,
    refresh: refreshSummary,
  } = useAsync(({ signal }) => analytics.summary(days, { signal }), [days]);

  const {
    data: mostBlocked,
    error: blockedError,
    loading: blockedLoading,
    refresh: refreshBlocked,
  } = useAsync(({ signal }) => analytics.mostBlocked(days, 10, { signal }), [days]);

  const { data: report } = useAsync(({ signal }) => analytics.dailyReport(null, { signal }), []);

  const chartData = useMemo(() => {
    const rows = mostBlocked || [];
    return {
      labels: rows.map((row) => row.camera_name),
      datasets: [
        {
          label: "Total blocked (minutes)",
          data: rows.map((row) => Number((row.total_blocked_s / 60).toFixed(1))),
          backgroundColor: theme.palette.error.main + "cc",
          borderRadius: 6,
        },
        {
          label: "Events",
          data: rows.map((row) => row.event_count),
          backgroundColor: theme.palette.warning.main + "cc",
          borderRadius: 6,
        },
      ],
    };
  }, [mostBlocked, theme]);

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      // Minutes and event counts share an axis only because they are both
      // "how bad was this exit" — the legend names which bar is which.
      scales: {
        x: {
          ticks: { color: theme.palette.text.secondary },
          grid: { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: theme.palette.text.secondary },
          grid: { color: theme.palette.divider },
        },
      },
      plugins: {
        legend: { labels: { color: theme.palette.text.secondary } },
      },
    }),
    [theme]
  );

  return (
    <Box>
      <PageHeader
        title="Analytics"
        subtitle="Which exits are obstructed most often, for how long, and how bad it got."
        actions={
          <TextField
            select
            size="small"
            label="Window"
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            sx={{ minWidth: 180 }}
          >
            {WINDOWS.map((window) => (
              <MenuItem key={window.value} value={window.value}>
                {window.label}
              </MenuItem>
            ))}
          </TextField>
        }
      />

      <ErrorState
        error={summaryError || blockedError}
        onRetry={() => {
          refreshSummary();
          refreshBlocked();
        }}
        title="Could not load analytics"
      />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Events"
            value={summaryLoading ? "…" : formatNumber(summary?.events_total)}
            hint={`${summary?.events_open ?? 0} still open`}
            icon={<EventNoteIcon />}
            color="warning"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Average blockage"
            value={summary ? formatDuration(summary.avg_duration_s) : "…"}
            hint={summary ? `longest ${formatDuration(summary.max_duration_s)}` : ""}
            icon={<TimerIcon />}
            color="secondary"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Worst accessibility"
            value={summary ? formatPct(summary.avg_min_accessibility_pct) : "…"}
            hint="average low point per event"
            icon={<DoorFrontIcon />}
            color="error"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Alerts sent"
            value={summaryLoading ? "…" : formatNumber(summary?.alerts_sent)}
            hint={`${summary?.currently_blocked ?? 0} blocked right now`}
            icon={<NotificationsIcon />}
            color="info"
          />
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={12}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>
                Most blocked exits
              </Typography>
              {blockedLoading && !mostBlocked ? (
                <Loading label="Aggregating…" height={280} />
              ) : !mostBlocked?.length ? (
                <EmptyState
                  title="No blockages recorded in this window"
                  description="Either every exit stayed clear, or nothing has been monitored long enough yet."
                />
              ) : (
                <Box sx={{ height: 320, mt: 2 }}>
                  <Bar data={chartData} options={chartOptions} />
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        {mostBlocked?.length > 0 && (
          <Grid size={12}>
            <Card>
              <CardContent sx={{ pb: 0 }}>
                <Typography variant="subtitle2">Breakdown</Typography>
              </CardContent>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Exit</TableCell>
                      <TableCell>Location</TableCell>
                      <TableCell align="right">Events</TableCell>
                      <TableCell align="right">Total blocked</TableCell>
                      <TableCell align="right">Average</TableCell>
                      <TableCell align="right">Longest</TableCell>
                      <TableCell align="right">Worst accessible</TableCell>
                      <TableCell align="right">Peak risk</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {mostBlocked.map((row) => (
                      <TableRow key={row.camera_id} hover>
                        <TableCell>
                          <Button
                            size="small"
                            component={RouterLink}
                            to={`/cameras/${row.camera_id}`}
                            sx={{ textTransform: "none", p: 0, minWidth: 0 }}
                          >
                            {row.camera_name}
                          </Button>
                        </TableCell>
                        <TableCell>{row.location || "—"}</TableCell>
                        <TableCell align="right">{row.event_count}</TableCell>
                        <TableCell align="right">{formatDuration(row.total_blocked_s)}</TableCell>
                        <TableCell align="right">{formatDuration(row.avg_duration_s)}</TableCell>
                        <TableCell align="right">{formatDuration(row.max_duration_s)}</TableCell>
                        <TableCell align="right">
                          {formatPct(row.min_accessibility_pct)}
                        </TableCell>
                        <TableCell align="right">
                          {Number(row.peak_risk_score ?? 0).toFixed(0)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Card>
          </Grid>
        )}

        <Grid size={12}>
          <Card>
            <CardContent sx={{ pb: 0 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="subtitle2">
                  Daily report{report?.report_date ? ` — ${report.report_date}` : ""}
                </Typography>
              </Stack>
            </CardContent>
            {report?.rows?.length ? (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Exit</TableCell>
                      <TableCell align="right">Events</TableCell>
                      <TableCell align="right">Total blocked</TableCell>
                      <TableCell align="right">Average</TableCell>
                      <TableCell align="right">Longest</TableCell>
                      <TableCell align="right">Worst accessible</TableCell>
                      <TableCell align="right">Alerts</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {report.rows.map((row) => (
                      <TableRow key={row.camera_id} hover>
                        <TableCell>{row.camera_name}</TableCell>
                        <TableCell align="right">{row.event_count}</TableCell>
                        <TableCell align="right">{formatDuration(row.total_blocked_s)}</TableCell>
                        <TableCell align="right">{formatDuration(row.avg_duration_s)}</TableCell>
                        <TableCell align="right">
                          {formatDuration(row.longest_blockage_s)}
                        </TableCell>
                        <TableCell align="right">
                          {formatPct(row.worst_accessibility_pct)}
                        </TableCell>
                        <TableCell align="right">{row.alerts_sent}</TableCell>
                      </TableRow>
                    ))}
                    {report.totals && (
                      <TableRow sx={{ "& td": { fontWeight: 700 } }}>
                        <TableCell>Total</TableCell>
                        <TableCell align="right">{report.totals.event_count}</TableCell>
                        <TableCell align="right">
                          {formatDuration(report.totals.total_blocked_s)}
                        </TableCell>
                        <TableCell align="right">
                          {formatDuration(report.totals.avg_duration_s)}
                        </TableCell>
                        <TableCell align="right">
                          {formatDuration(report.totals.longest_blockage_s)}
                        </TableCell>
                        <TableCell align="right">
                          {formatPct(report.totals.worst_accessibility_pct)}
                        </TableCell>
                        <TableCell align="right">{report.totals.alerts_sent}</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <EmptyState
                title="Nothing recorded today"
                description="The daily report covers the current UTC day."
              />
            )}
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
