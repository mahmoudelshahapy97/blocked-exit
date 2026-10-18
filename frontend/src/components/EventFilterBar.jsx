import { useMemo } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Grid from "@mui/material/Grid2";
import ListItemText from "@mui/material/ListItemText";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import FilterAltOffIcon from "@mui/icons-material/FilterAltOff";

import { cameras as camerasApi } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";

/** The query parameters every filtered endpoint understands (services/filters.py). */
export const FILTER_KEYS = [
  "camera_id",
  "start_date",
  "end_date",
  "start_time",
  "end_time",
  "location",
  "area",
  "building",
  "floor_level",
  "zone",
];

const HIERARCHY = [
  { key: "location", list: "locations", label: "Location" },
  { key: "area", list: "areas", label: "Area" },
  { key: "building", list: "buildings", label: "Building" },
  { key: "floor_level", list: "floor_levels", label: "Floor" },
  { key: "zone", list: "zones", label: "Zone" },
];

const split = (value) => (value ? String(value).split(",").filter(Boolean) : []);

/** Pick the filter keys out of anything (URLSearchParams entries, state…). */
export function pickFilters(source) {
  const out = {};
  FILTER_KEYS.forEach((key) => {
    const value = typeof source.get === "function" ? source.get(key) : source[key];
    if (value) out[key] = value;
  });
  return out;
}

export const hasFilters = (filters) => FILTER_KEYS.some((key) => filters[key]);

function MultiSelect({ label, options, value, onChange, renderOption = (o) => o.label }) {
  const selected = split(value);
  return (
    <TextField
      select
      size="small"
      fullWidth
      label={label}
      value={selected}
      onChange={(event) => onChange(event.target.value.join(","))}
      SelectProps={{
        multiple: true,
        renderValue: (values) =>
          values
            .map((v) => options.find((o) => String(o.value) === v)?.label ?? v)
            .join(", "),
      }}
      disabled={!options.length && !selected.length}
    >
      {options.map((option) => (
        <MenuItem key={option.value} value={String(option.value)} dense>
          <Checkbox size="small" checked={selected.includes(String(option.value))} />
          <ListItemText primary={renderOption(option)} />
        </MenuItem>
      ))}
    </TextField>
  );
}

/**
 * Date range, time-of-day window, exits and the location → zone hierarchy —
 * the platform's event filter. Each hierarchy level lists only the values
 * left under the levels chosen above it.
 *
 * `value` is a plain object of query-string values (comma-joined lists), so a
 * page can keep it in the URL and hand it straight to the API.
 */
export default function EventFilterBar({ value, onChange }) {
  const set = (key) => (next) => {
    const updated = { ...value, [key]: next };
    // Narrowing a level can orphan the choices below it; drop those.
    const level = HIERARCHY.findIndex((h) => h.key === key);
    if (level >= 0) HIERARCHY.slice(level + 1).forEach((h) => delete updated[h.key]);
    Object.keys(updated).forEach((k) => !updated[k] && delete updated[k]);
    onChange(updated);
  };

  const parents = useMemo(
    () => ({
      location: value.location,
      area: value.area,
      building: value.building,
      floor_level: value.floor_level,
    }),
    [value.location, value.area, value.building, value.floor_level]
  );
  const { data: hierarchy } = useAsync(
    (opts) => camerasApi.hierarchy(parents, opts),
    [JSON.stringify(parents)]
  );
  const { data: cameraList } = useAsync((opts) => camerasApi.list(undefined, opts), []);

  const cameraOptions = useMemo(() => {
    // Only exits inside the chosen hierarchy are worth offering.
    const within = (camera) =>
      HIERARCHY.every(({ key }) => {
        const chosen = split(value[key]);
        return !chosen.length || chosen.includes(camera[key]);
      });
    return (cameraList || [])
      .filter(within)
      .map((camera) => ({ value: camera.id, label: camera.name }));
  }, [cameraList, value]);

  const dateField = (key, label, type) => (
    <TextField
      size="small"
      fullWidth
      type={type}
      label={label}
      value={value[key] || ""}
      onChange={(event) => set(key)(event.target.value)}
      InputLabelProps={{ shrink: true }}
    />
  );

  return (
    <Grid container spacing={1.5} alignItems="center">
      <Grid size={{ xs: 6, sm: 3, lg: 2 }}>{dateField("start_date", "From", "date")}</Grid>
      <Grid size={{ xs: 6, sm: 3, lg: 2 }}>{dateField("end_date", "To", "date")}</Grid>
      <Grid size={{ xs: 6, sm: 3, lg: 2 }}>
        <Tooltip title="Without a From date: every day from this time">
          <Box>{dateField("start_time", "From time", "time")}</Box>
        </Tooltip>
      </Grid>
      <Grid size={{ xs: 6, sm: 3, lg: 2 }}>
        <Tooltip title="Without a To date: every day until this time (may wrap midnight)">
          <Box>{dateField("end_time", "To time", "time")}</Box>
        </Tooltip>
      </Grid>
      <Grid size={{ xs: 12, sm: 6, lg: 4 }}>
        <MultiSelect
          label="Exits"
          options={cameraOptions}
          value={value.camera_id}
          onChange={set("camera_id")}
        />
      </Grid>
      {HIERARCHY.map(({ key, list, label }) => (
        <Grid key={key} size={{ xs: 6, sm: 4, lg: 2 }}>
          <MultiSelect
            label={label}
            options={(hierarchy?.[list] || []).map((v) => ({ value: v, label: v }))}
            value={value[key]}
            onChange={set(key)}
          />
        </Grid>
      ))}
      <Grid size={{ xs: 12, sm: 2, lg: 2 }}>
        <Button
          fullWidth
          color="inherit"
          startIcon={<FilterAltOffIcon />}
          disabled={!hasFilters(value)}
          onClick={() => onChange({})}
        >
          Clear
        </Button>
      </Grid>
    </Grid>
  );
}
