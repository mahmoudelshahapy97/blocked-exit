import { useCallback, useMemo, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonGroup from "@mui/material/ButtonGroup";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid2";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import dayjs from "dayjs";

import EventNoteIcon from "@mui/icons-material/EventNote";
import TimerIcon from "@mui/icons-material/Timer";
import DoorFrontIcon from "@mui/icons-material/DoorFront";
import NotificationsIcon from "@mui/icons-material/NotificationsActive";

import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip as ChartTooltip,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";

import { analytics } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import EventFilterBar, { FILTER_KEYS, pickFilters } from "../components/EventFilterBar";
import ChartCard from "../components/charts/ChartCard";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { EventStatusChip } from "../components/StatusChips";
import { useChartTheme } from "../utils/chartTheme";
import { formatDateTime, formatDuration, formatNumber, formatPct } from "../utils/format";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Filler,
  ChartTooltip,
  Legend
);

const TABS = [
  { value: "overview", get label() { return i18n.t("analytics.overview"); } },
  { value: "incidents", get label() { return i18n.t("analytics.incidentsPerExit"); } },
  { value: "response", get label() { return i18n.t("analytics.responseTimes"); } },
  { value: "breakdown", get label() { return i18n.t("analytics.blockedTime"); } },
  { value: "confidence", get label() { return i18n.t("analytics.confidenceAudit"); } },
  { value: "daily", get label() { return i18n.t("analytics.dailyReport"); } },
];

const QUICK_RANGES = [
  { days: 1, get label() { return i18n.t("analytics.today"); } },
  { days: 7, get label() { return i18n.t("analytics.7Days"); } },
  { days: 30, get label() { return i18n.t("analytics.30Days"); } },
  { days: 90, get label() { return i18n.t("analytics.90Days"); } },
];

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pct = (fraction, digits = 0) =>
  fraction === null || fraction === undefined ? "—" : formatPct(fraction * 100, digits);
const minutes = (seconds) => Number(((seconds || 0) / 60).toFixed(1));

/** One fetch per chart, refetched whenever the shared filters change. */
function useFiltered(fetcher, filters, extra = []) {
  return useAsync((opts) => fetcher(filters, opts), [JSON.stringify(filters), ...extra]);
}

function SimpleTable({ columns, rows, rowKey }) {
  return (
    <TableContainer sx={{ maxHeight: 420 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            {columns.map((c) => (
              <TableCell key={c.label} align={c.align}>
                {c.label}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={rowKey ? rowKey(row) : i} hover>
              {columns.map((c) => (
                <TableCell key={c.label} align={c.align} sx={{ fontVariantNumeric: "tabular-nums" }}>
                  {c.render(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

// --- overview -----------------------------------------------------------------
function TrendChart({ filters }) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const [bucket, setBucket] = useState("");
  const { data, error, loading, refresh } = useFiltered(
    (f, opts) => analytics.trend(f, bucket || undefined, opts),
    filters,
    [bucket]
  );
  const points = data?.points || [];
  const label = (p) =>
    dayjs(p.bucket_start).format(data?.bucket === "hour" ? "MMM D HH:mm" : "MMM D");

  return (
    <ChartCard
      title={t("analytics.incidentsOverTime")}
      subtitle={data ? t("analytics.perBucketTimezoneTime", { bucket: data.bucket, timezone: data.timezone }) : undefined}
      loading={loading}
      error={error}
      onRetry={refresh}
      empty={data ? points.every((p) => p.incidents === 0) : undefined}
      actions={
        <ButtonGroup size="small" sx={{ mr: 1 }}>
          {[
            ["", "Auto"],
            ["hour", "Hour"],
            ["day", "Day"],
          ].map(([value, text]) => (
            <Button
              key={text}
              variant={bucket === value ? "contained" : "outlined"}
              onClick={() => setBucket(value)}
            >
              {text}
            </Button>
          ))}
        </ButtonGroup>
      }
      chart={
        <Line
          data={{
            labels: points.map(label),
            datasets: [
              { label: t("analytics.incidents"), data: points.map((p) => p.incidents), ...ct.line(ct.series[0]) },
              { label: t("analytics.resolved"), data: points.map((p) => p.resolved), ...ct.line(ct.series[2]) },
            ],
          }}
          options={{
            ...ct.options({ legend: true }),
            scales: {
              ...ct.options().scales,
              x: { ...ct.options().scales.x, ticks: { color: ct.text, maxTicksLimit: 10, autoSkip: true } },
              y: { ...ct.options().scales.y, ticks: { color: ct.text, precision: 0 } },
            },
          }}
        />
      }
      table={
        <SimpleTable
          rows={points.filter((p) => p.incidents)}
          columns={[
            { label: data?.bucket === "hour" ? "Hour" : "Day", render: label },
            { label: t("analytics.incidents"), align: "right", render: (p) => p.incidents },
            { label: t("analytics.resolved"), align: "right", render: (p) => p.resolved },
          ]}
        />
      }
    />
  );
}

function Heatmap({ filters }) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const { data, error, loading, refresh } = useFiltered(analytics.heatmap, filters);
  const cells = useMemo(() => {
    const map = new Map((data || []).map((c) => [`${c.weekday}-${c.hour}`, c.incidents]));
    return map;
  }, [data]);
  const max = Math.max(1, ...(data || []).map((c) => c.incidents));

  const grid = (
    <Box sx={{ overflowX: "auto" }}>
      <Box
        role="grid"
        aria-label={t("analytics.incidentsByWeekdayAndHour")}
        sx={{
          display: "grid",
          gridTemplateColumns: "36px repeat(24, minmax(14px, 1fr))",
          gap: "2px",
          minWidth: 420,
        }}
      >
        <Box />
        {Array.from({ length: 24 }, (_, h) => (
          <Typography
            key={h}
            variant="caption"
            color="text.secondary"
            sx={{ textAlign: "center", fontSize: 10, visibility: h % 3 ? "hidden" : "visible" }}
          >
            {String(h).padStart(2, "0")}
          </Typography>
        ))}
        {WEEKDAYS.map((day, w) => [
          <Typography key={day} variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
            {day}
          </Typography>,
          ...Array.from({ length: 24 }, (_, h) => {
            const n = cells.get(`${w}-${h}`) || 0;
            const text = `${day} ${String(h).padStart(2, "0")}:00–${String(h + 1).padStart(2, "0")}:00 · ${t("analytics.incidentCount", { count: n })}`;
            return (
              <Tooltip key={`${w}-${h}`} title={text} disableInteractive>
                <Box
                  role="gridcell"
                  aria-label={text}
                  tabIndex={n ? 0 : -1}
                  sx={{
                    height: 22,
                    borderRadius: "3px",
                    bgcolor: n ? ct.sequential(n / max) : "action.hover",
                    outlineOffset: 1,
                    "&:hover, &:focus-visible": { outline: "2px solid", outlineColor: "text.primary" },
                  }}
                />
              </Tooltip>
            );
          }),
        ])}
      </Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          {t("analytics.fewer")}
        </Typography>
        <Stack direction="row" spacing="2px">
          {ct.ramp.map((color) => (
            <Box key={color} sx={{ width: 16, height: 10, borderRadius: "2px", bgcolor: color }} />
          ))}
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {t("analytics.moreBusiestSlot", { count: max })}
        </Typography>
      </Stack>
    </Box>
  );

  return (
    <ChartCard
      title={t("analytics.whenExitsGetBlocked")}
      subtitle={t("analytics.incidentsByWeekdayAndHour2")}
      loading={loading}
      error={error}
      onRetry={refresh}
      empty={data ? data.length === 0 : undefined}
      height="auto"
      chart={grid}
      table={
        <SimpleTable
          rows={[...(data || [])].sort((a, b) => b.incidents - a.incidents)}
          columns={[
            { label: t("analytics.weekday"), render: (c) => WEEKDAYS[c.weekday] },
            { label: t("analytics.hour"), render: (c) => `${String(c.hour).padStart(2, "0")}:00` },
            { label: t("analytics.incidents"), align: "right", render: (c) => c.incidents },
          ]}
        />
      }
    />
  );
}

function OverviewTab({ filters }) {
  const { t } = useTranslation();
  const { data: summary, error, refresh } = useFiltered(
    // Without a From date the summary covers everything (ten years back).
    (f, opts) => analytics.summary(f.start_date ? 7 : 3650, opts, f),
    filters
  );
  return (
    <Stack spacing={2}>
      <ErrorState error={error} onRetry={refresh} title={t("analytics.couldNotLoadTheSummary")} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label={t("analytics.incidents")}
            value={summary ? formatNumber(summary.events_total) : "…"}
            hint={summary ? t("analytics.eventsOpenStillBlocked", { events_open: summary.events_open }) : ""}
            icon={<EventNoteIcon />}
            color="warning"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label={t("analytics.averageBlockage")}
            value={summary ? formatDuration(summary.avg_duration_s) : "…"}
            hint={summary ? t("analytics.longestV0", { v0: formatDuration(summary.max_duration_s) }) : ""}
            icon={<TimerIcon />}
            color="secondary"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label={t("analytics.worstAccessibility")}
            value={summary ? formatPct(summary.avg_min_accessibility_pct) : "…"}
            hint={t("analytics.averageLowPointPerIncident")}
            icon={<DoorFrontIcon />}
            color="error"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label={t("analytics.alertsSent")}
            value={summary ? formatNumber(summary.alerts_sent) : "…"}
            hint={summary ? t("analytics.camerasMonitoredOfCamerasTotal", { cameras_monitored: summary.cameras_monitored, cameras_total: summary.cameras_total }) : ""}
            icon={<NotificationsIcon />}
            color="info"
          />
        </Grid>
      </Grid>
      <TrendChart filters={filters} />
      <Heatmap filters={filters} />
    </Stack>
  );
}

// --- incidents per exit -----------------------------------------------------------
function IncidentsTab({ filters }) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const { data, error, loading, refresh } = useFiltered(analytics.incidentsPerCamera, filters);
  const rows = data || [];
  const totals = rows.reduce(
    (acc, r) => ({
      events: acc.events + r.events,
      acknowledged: acc.acknowledged + r.acknowledged,
      resolved: acc.resolved + r.resolved,
    }),
    { events: 0, acknowledged: 0, resolved: 0 }
  );
  const place = (r) =>
    [r.location, r.building, r.floor_level && `Floor ${r.floor_level}`, r.zone].filter(Boolean).join(" · ");

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip label={t("analytics.exitCount", { count: rows.length })} />
        <Chip label={t("analytics.eventsIncidents", { events: totals.events })} />
        <Chip label={t("analytics.acknowledgedAcknowledged", { acknowledged: totals.acknowledged })} />
        <Chip label={t("analytics.resolvedResolved", { resolved: totals.resolved })} />
        <Chip label={t("analytics.v0Open", { v0: totals.events - totals.resolved })} variant="outlined" />
      </Stack>
      <ChartCard
        title={t("analytics.incidentsPerExit")}
        subtitle={t("analytics.blockageEpisodesAndHowMany")}
        loading={loading}
        error={error}
        onRetry={refresh}
        empty={data ? rows.length === 0 : undefined}
        height={Math.max(260, rows.length * 56)}
        chart={
          <Bar
            data={{
              labels: rows.map((r) => r.camera_name),
              datasets: [
                { label: t("analytics.incidents"), data: rows.map((r) => r.events), ...ct.bar(ct.series[0]) },
                { label: t("analytics.acknowledged"), data: rows.map((r) => r.acknowledged), ...ct.bar(ct.series[1]) },
                { label: t("analytics.resolved"), data: rows.map((r) => r.resolved), ...ct.bar(ct.series[2]) },
              ],
            }}
            options={{
              ...ct.options({ legend: true, horizontal: true }),
              scales: {
                ...ct.options({ horizontal: true }).scales,
                x: { ...ct.options({ horizontal: true }).scales.x, ticks: { color: ct.text, precision: 0 } },
              },
            }}
          />
        }
        table={
          <SimpleTable
            rows={rows}
            rowKey={(r) => r.camera_id}
            columns={[
              {
                label: t("analytics.exit"),
                render: (r) => (
                  <Button
                    size="small"
                    component={RouterLink}
                    to={`/events?camera_id=${r.camera_id}`}
                    sx={{ textTransform: "none", p: 0, minWidth: 0 }}
                  >
                    {r.camera_name}
                  </Button>
                ),
              },
              { label: t("analytics.place"), render: (r) => place(r) || "—" },
              { label: t("analytics.incidents"), align: "right", render: (r) => r.events },
              { label: t("analytics.acknowledged"), align: "right", render: (r) => r.acknowledged },
              { label: t("analytics.resolved"), align: "right", render: (r) => r.resolved },
            ]}
          />
        }
      />
    </Stack>
  );
}

// --- response times ------------------------------------------------------------------
function ResponseTab({ filters }) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const { data, error, loading, refresh } = useFiltered(analytics.responseTimes, filters);
  const s = data?.summary;
  const rows = (data?.per_camera || []).filter((r) => r.acknowledged);

  return (
    <Stack spacing={2}>
      <ErrorState error={error} onRetry={refresh} title={t("analytics.couldNotLoadResponseTimes")} />
      <Grid container spacing={2}>
        {[
          [t("analytics.timeToAck"), s?.ack_median_s, s?.ack_p90_s, t("analytics.ackOf", { acknowledged: s?.acknowledged ?? 0, incidents: s?.incidents ?? 0 })],
          [t("analytics.timeToResolve"), s?.resolve_median_s, s?.resolve_p90_s, t("analytics.resolvedOpen", { resolved: s?.resolved ?? 0, open: s?.open ?? 0 })],
        ].map(([label, median, p90, hint]) => (
          <Grid key={label} size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <Typography variant="overline" color="text.secondary">
                  {label}
                </Typography>
                <Stack direction="row" spacing={4} alignItems="baseline" sx={{ mt: 0.5 }}>
                  <Box>
                    <Typography sx={{ fontSize: 48, fontWeight: 700, lineHeight: 1.1 }}>
                      {s ? formatDuration(median) : "…"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {t("analytics.median")}
                    </Typography>
                  </Box>
                  <Box>
                    <Typography variant="h5">{s ? formatDuration(p90) : "…"}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {t("analytics.90thPercentile")}
                    </Typography>
                  </Box>
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  {hint}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      <ChartCard
        title={t("analytics.medianResponsePerExit")}
        subtitle={t("analytics.minutesFromTheBlockageBeing")}
        loading={loading}
        error={null}
        empty={data ? rows.length === 0 : undefined}
        emptyText={t("analytics.noIncidentInThisRange")}
        height={Math.max(220, rows.length * 48)}
        chart={
          <Bar
            data={{
              labels: rows.map((r) => r.camera_name),
              datasets: [
                { label: t("analytics.toAcknowledge"), data: rows.map((r) => minutes(r.ack_median_s)), ...ct.bar(ct.series[0]) },
                { label: t("analytics.toResolve"), data: rows.map((r) => minutes(r.resolve_median_s)), ...ct.bar(ct.series[1]) },
              ],
            }}
            options={ct.options({ legend: true, horizontal: true, xTitle: "minutes" })}
          />
        }
        table={
          <SimpleTable
            rows={data?.per_camera || []}
            rowKey={(r) => r.camera_id}
            columns={[
              { label: t("analytics.exit"), render: (r) => r.camera_name },
              { label: t("analytics.incidents"), align: "right", render: (r) => r.incidents },
              { label: t("analytics.ackMedian"), align: "right", render: (r) => formatDuration(r.ack_median_s) },
              { label: t("analytics.ackP90"), align: "right", render: (r) => formatDuration(r.ack_p90_s) },
              { label: t("analytics.resolveMedian"), align: "right", render: (r) => formatDuration(r.resolve_median_s) },
              { label: t("analytics.resolveP90"), align: "right", render: (r) => formatDuration(r.resolve_p90_s) },
              { label: t("analytics.open"), align: "right", render: (r) => r.open },
            ]}
          />
        }
      />
    </Stack>
  );
}

// --- blocked time ------------------------------------------------------------------------
const durationLabel = (bin) => {
  const short = (s) => (s < 60 ? `${s}s` : `${s / 60}m`);
  if (bin.max == null) return `${short(bin.min)}+`;
  return bin.min === 0 ? `<${short(bin.max)}` : `${short(bin.min)}–${short(bin.max)}`;
};

function BreakdownTab({ filters }) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const { data, error, loading, refresh } = useFiltered(analytics.breakdown, filters);
  const perCamera = data?.per_camera || [];
  const histogram = data?.duration_histogram || [];
  const objects = data?.top_objects || [];
  const empty = data ? perCamera.length === 0 : undefined;
  const common = { loading, error, onRetry: refresh, empty };

  return (
    <Grid container spacing={2}>
      <Grid size={12}>
        <ChartCard
          {...common}
          title={t("analytics.blockedTimePerExit")}
          subtitle={t("analytics.totalMinutesObstructedOngoingBlockag")}
          height={Math.max(220, perCamera.length * 40)}
          chart={
            <Bar
              data={{
                labels: perCamera.map((r) => r.camera_name),
                datasets: [
                  { label: t("analytics.minutesBlocked"), data: perCamera.map((r) => minutes(r.total_blocked_s)), ...ct.bar(ct.series[0]) },
                ],
              }}
              options={ct.options({ horizontal: true, xTitle: "minutes" })}
            />
          }
          table={
            <SimpleTable
              rows={perCamera}
              rowKey={(r) => r.camera_id}
              columns={[
                { label: t("analytics.exit"), render: (r) => r.camera_name },
                { label: t("analytics.episodes"), align: "right", render: (r) => r.episodes },
                { label: t("analytics.totalBlocked"), align: "right", render: (r) => formatDuration(r.total_blocked_s) },
                { label: t("analytics.average"), align: "right", render: (r) => formatDuration(r.avg_duration_s) },
                { label: t("analytics.longest"), align: "right", render: (r) => formatDuration(r.max_duration_s) },
                { label: t("analytics.worstAccessible"), align: "right", render: (r) => formatPct(r.worst_accessibility_pct) },
                { label: t("analytics.reachedFull"), align: "right", render: (r) => r.fully_blocked },
              ]}
            />
          }
        />
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard
          {...common}
          title={t("analytics.howLongBlockagesLast")}
          subtitle={t("analytics.episodesByDuration")}
          height={260}
          chart={
            <Bar
              data={{
                labels: histogram.map(durationLabel),
                datasets: [{ label: t("analytics.episodes"), data: histogram.map((b) => b.count), ...ct.bar(ct.series[0]) }],
              }}
              options={{
                ...ct.options(),
                scales: {
                  ...ct.options().scales,
                  y: { ...ct.options().scales.y, ticks: { color: ct.text, precision: 0 } },
                },
              }}
            />
          }
          table={
            <SimpleTable
              rows={histogram}
              columns={[
                { label: t("analytics.duration"), render: durationLabel },
                { label: t("analytics.episodes"), align: "right", render: (b) => b.count },
              ]}
            />
          }
        />
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard
          {...common}
          empty={data ? objects.length === 0 : undefined}
          title={t("analytics.whatBlocksExits")}
          subtitle={t("analytics.episodesEachKindOfObject")}
          height={Math.max(220, objects.length * 32)}
          chart={
            <Bar
              data={{
                labels: objects.map((o) => o.object),
                datasets: [{ label: t("analytics.episodes"), data: objects.map((o) => o.episodes), ...ct.bar(ct.series[0]) }],
              }}
              options={{
                ...ct.options({ horizontal: true }),
                scales: {
                  ...ct.options({ horizontal: true }).scales,
                  x: { ...ct.options({ horizontal: true }).scales.x, ticks: { color: ct.text, precision: 0 } },
                },
              }}
            />
          }
          table={
            <SimpleTable
              rows={objects}
              columns={[
                { label: t("analytics.object"), render: (o) => o.object },
                { label: t("analytics.episodes"), align: "right", render: (o) => o.episodes },
              ]}
            />
          }
        />
      </Grid>
    </Grid>
  );
}

// --- confidence audit ----------------------------------------------------------------------
const LOG_ROWS = 8;

function ConfidenceTab({ filters }) {
  const { t } = useTranslation();
  const ct = useChartTheme();
  const { data, error, loading, refresh } = useFiltered(analytics.confidenceAudit, filters);
  const [page, setPage] = useState(0);
  const s = data?.summary;
  const perCamera = data?.per_camera || [];
  const histogram = data?.histogram || [];
  const log = data?.per_event || [];
  const empty = data ? s.scored_events === 0 : undefined;
  const common = { loading, error, onRetry: refresh, empty, emptyText: t("analytics.noIncidentInThisRange2") };

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 6, md: 3 }}>
        <StatCard label={t("analytics.meanConfidence")} value={pct(s?.avg_confidence)} hint={t("analytics.peakDetectionPerIncident")} />
      </Grid>
      <Grid size={{ xs: 6, md: 3 }}>
        <StatCard
          label={t("analytics.auditedIncidents")}
          value={s ? formatNumber(s.scored_events) : "…"}
          hint={s ? t("analytics.ofEventsInRange", { events: s.events }) : ""}
        />
      </Grid>
      <Grid size={{ xs: 6, md: 3 }}>
        <StatCard
          label={t("analytics.lowConfidence")}
          value={s ? formatNumber(s.low_confidence) : "…"}
          hint={s ? t("analytics.belowV0V1OfAudited", { v0: pct(s.low_confidence_cutoff), v1: pct(s.low_confidence_share, 1) }) : ""}
        />
      </Grid>
      <Grid size={{ xs: 6, md: 3 }}>
        <StatCard
          label={t("analytics.range")}
          value={s?.scored_events ? `${pct(s.min_confidence)}–${pct(s.max_confidence)}` : "—"}
          hint={s ? t("analytics.detectorThresholdV0", { v0: pct(s.threshold) }) : ""}
        />
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard
          {...common}
          title={t("analytics.meanConfidencePerExit")}
          height={Math.max(220, perCamera.length * 36)}
          chart={
            <Bar
              data={{
                labels: perCamera.map((r) => r.camera_name),
                datasets: [
                  { label: t("analytics.meanConfidence"), data: perCamera.map((r) => Math.round((r.avg_confidence || 0) * 100)), ...ct.bar(ct.series[0]) },
                ],
              }}
              options={{
                ...ct.options({ horizontal: true }),
                scales: {
                  ...ct.options({ horizontal: true }).scales,
                  x: { ...ct.options({ horizontal: true }).scales.x, max: 100, ticks: { color: ct.text, callback: (v) => `${v}%` } },
                },
              }}
            />
          }
          table={
            <SimpleTable
              rows={perCamera}
              rowKey={(r) => r.camera_id}
              columns={[
                { label: t("analytics.exit"), render: (r) => r.camera_name },
                { label: t("analytics.audited"), align: "right", render: (r) => r.events },
                { label: t("analytics.mean"), align: "right", render: (r) => pct(r.avg_confidence) },
                { label: t("analytics.min"), align: "right", render: (r) => pct(r.min_confidence) },
                { label: t("analytics.max"), align: "right", render: (r) => pct(r.max_confidence) },
                { label: t("analytics.low"), align: "right", render: (r) => r.low_confidence },
              ]}
            />
          }
        />
      </Grid>
      <Grid size={{ xs: 12, md: 6 }}>
        <ChartCard
          {...common}
          title={t("analytics.confidenceDistribution")}
          subtitle={t("analytics.incidentsByPeakDetectionConfidence")}
          height={260}
          chart={
            <Bar
              data={{
                labels: histogram.map((b) => `${Math.round(b.min * 100)}–${Math.round(b.max * 100)}`),
                datasets: [{ label: t("analytics.incidents"), data: histogram.map((b) => b.count), ...ct.bar(ct.series[0]) }],
              }}
              options={{
                ...ct.options({ xTitle: t("analytics.peakConfidencePct") }),
                scales: {
                  ...ct.options({ xTitle: t("analytics.peakConfidencePct") }).scales,
                  x: {
                    ...ct.options({ xTitle: t("analytics.peakConfidencePct") }).scales.x,
                    ticks: { color: ct.text, maxRotation: 0, autoSkip: false, font: { size: 10 } },
                  },
                  y: { ...ct.options().scales.y, ticks: { color: ct.text, precision: 0 } },
                },
              }}
            />
          }
          table={
            <SimpleTable
              rows={histogram}
              columns={[
                { label: t("analytics.confidence"), render: (b) => `${Math.round(b.min * 100)}–${Math.round(b.max * 100)}%` },
                { label: t("analytics.incidents"), align: "right", render: (b) => b.count },
              ]}
            />
          }
        />
      </Grid>
      <Grid size={12}>
        <ChartCard
          {...common}
          title={t("analytics.incidentConfidenceLog")}
          subtitle={t("analytics.latest200AuditedIncidents")}
          table={
            <>
              <SimpleTable
                rows={log.slice(page * LOG_ROWS, page * LOG_ROWS + LOG_ROWS)}
                rowKey={(e) => e.event_id}
                columns={[
                  { label: "#", render: (e) => e.event_id },
                  { label: t("analytics.exit"), render: (e) => e.camera_name },
                  { label: t("analytics.started"), render: (e) => formatDateTime(e.started_at) },
                  {
                    label: t("analytics.peak"),
                    align: "right",
                    render: (e) => (
                      <Box component="span" sx={{ color: s && e.confidence < s.low_confidence_cutoff ? "warning.main" : undefined, fontWeight: 600 }}>
                        {pct(e.confidence)}
                      </Box>
                    ),
                  },
                  { label: t("analytics.mean"), align: "right", render: (e) => pct(e.avg_confidence) },
                  { label: t("analytics.status"), render: (e) => <EventStatusChip status={e.status} /> },
                ]}
              />
              <TablePagination
                component="div"
                count={log.length}
                page={Math.min(page, Math.max(0, Math.ceil(log.length / LOG_ROWS) - 1))}
                rowsPerPage={LOG_ROWS}
                rowsPerPageOptions={[LOG_ROWS]}
                onPageChange={(_, p) => setPage(p)}
              />
            </>
          }
        />
      </Grid>
    </Grid>
  );
}

// --- daily report ---------------------------------------------------------------------------
function DailyTab({ filters }) {
  const { t } = useTranslation();
  const [reportDate, setReportDate] = useState("");
  const { data: report, error, loading, refresh } = useFiltered(
    (f, opts) => analytics.dailyReport(reportDate || null, opts, f),
    filters,
    [reportDate]
  );

  return (
    <Card>
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2} sx={{ mb: 2 }}>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              {t("analytics.dailyReportV0", { v0: report?.report_date ? ` — ${report.report_date}` : "" })}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t("analytics.everyExitIncludingThoseWith")}
            </Typography>
          </Box>
          <TextField
            size="small"
            type="date"
            label={t("analytics.day")}
            value={reportDate}
            onChange={(e) => setReportDate(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
        </Stack>
        <ErrorState error={error} onRetry={refresh} />
        {loading && !report ? (
          <Loading label={t("analytics.buildingTheReport")} />
        ) : report?.rows?.length ? (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("analytics.exit")}</TableCell>
                  <TableCell align="right">{t("analytics.incidents")}</TableCell>
                  <TableCell align="right">{t("analytics.totalBlocked")}</TableCell>
                  <TableCell align="right">{t("analytics.average")}</TableCell>
                  <TableCell align="right">{t("analytics.longest")}</TableCell>
                  <TableCell align="right">{t("analytics.worstAccessible")}</TableCell>
                  <TableCell align="right">{t("analytics.alerts")}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody sx={{ "& td": { fontVariantNumeric: "tabular-nums" } }}>
                {[...report.rows, ...(report.totals ? [{ ...report.totals, camera_name: "Total" }] : [])].map((row) => (
                  <TableRow
                    key={row.camera_id}
                    hover
                    sx={row.camera_id === 0 ? { "& td": { fontWeight: 700 } } : undefined}
                  >
                    <TableCell>{row.camera_name}</TableCell>
                    <TableCell align="right">{row.event_count}</TableCell>
                    <TableCell align="right">{formatDuration(row.total_blocked_s)}</TableCell>
                    <TableCell align="right">{formatDuration(row.avg_duration_s)}</TableCell>
                    <TableCell align="right">{formatDuration(row.longest_blockage_s)}</TableCell>
                    <TableCell align="right">{formatPct(row.worst_accessibility_pct)}</TableCell>
                    <TableCell align="right">{row.alerts_sent}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <EmptyState title={t("analytics.noExitsMatch")} description={t("analytics.clearTheExitOrLocation")} />
        )}
      </CardContent>
    </Card>
  );
}

// --- page -------------------------------------------------------------------------------------
export default function Analytics() {
  const { t } = useTranslation();
  // Filters and tab live in the URL: a view worth sharing is a link.
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => pickFilters(searchParams), [searchParams]);
  const tab = searchParams.get("tab") || "overview";

  const update = useCallback(
    (updates) =>
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        Object.entries(updates).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
        return next;
      }),
    [setSearchParams]
  );
  const setFilters = useCallback(
    (next) => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, next[k] || ""]))),
    [update]
  );
  const quickRange = (days) =>
    update({
      start_date: dayjs().subtract(days - 1, "day").format("YYYY-MM-DD"),
      end_date: dayjs().format("YYYY-MM-DD"),
      start_time: "",
      end_time: "",
    });
  const activeRange = QUICK_RANGES.find(
    (r) =>
      filters.start_date === dayjs().subtract(r.days - 1, "day").format("YYYY-MM-DD") &&
      filters.end_date === dayjs().format("YYYY-MM-DD")
  )?.days;

  const panels = {
    overview: <OverviewTab filters={filters} />,
    incidents: <IncidentsTab filters={filters} />,
    response: <ResponseTab filters={filters} />,
    breakdown: <BreakdownTab filters={filters} />,
    confidence: <ConfidenceTab filters={filters} />,
    daily: <DailyTab filters={filters} />,
  };

  return (
    <Box>
      <PageHeader
        title={t("analytics.analytics")}
        subtitle={t("analytics.whichExitsGetBlockedWhen")}
        actions={
          <ButtonGroup size="small">
            {QUICK_RANGES.map((r) => (
              <Button
                key={r.days}
                variant={activeRange === r.days ? "contained" : "outlined"}
                onClick={() => quickRange(r.days)}
              >
                {r.label}
              </Button>
            ))}
            <Button
              variant={!filters.start_date && !filters.end_date ? "contained" : "outlined"}
              onClick={() => update({ start_date: "", end_date: "" })}
            >
              {t("analytics.allTime")}
            </Button>
          </ButtonGroup>
        }
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <EventFilterBar value={filters} onChange={setFilters} />
      </Card>

      <Tabs
        value={tab}
        onChange={(_, value) => update({ tab: value === "overview" ? "" : value })}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ mb: 2 }}
      >
        {TABS.map((t) => (
          <Tab key={t.value} value={t.value} label={t.label} />
        ))}
      </Tabs>

      {panels[tab] ?? panels.overview}
    </Box>
  );
}
