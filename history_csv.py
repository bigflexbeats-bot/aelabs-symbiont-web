"""Read and normalize the canonical AELABS GIT LOG CSV for the web trend.

The parser deliberately uses timestamps written in the CSV. It never fills
missing timestamps with the server clock or the time at which GitHub was polled.
"""
from __future__ import annotations

import csv
import io
import json
import math
from typing import Any


def clean_cell(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    # AELABS preserves timestamps as Excel text cells: ="20.10.2026 14:05:10".
    if text.startswith('="') and text.endswith('"') and len(text) >= 3:
        text = text[2:-1].replace('""', '"').strip()
    return text or None


def number_cell(value: Any) -> float | None:
    text = clean_cell(value)
    if text is None:
        return None
    try:
        number = float(text.replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(row: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = clean_cell(row.get(name))
        if value is not None:
            return value
    return None


def downsample_history(items: list[dict[str, Any]], max_points: int = 2400) -> list[dict[str, Any]]:
    """Keep the full time span while choosing real rows that preserve each signal's extrema."""
    if len(items) <= max_points:
        return items
    metric_keys = ('ph', 'do_mg_l', 'do_sat_pct', 'temperature_c', 'microcheck_od', 'rpm')
    bucket_count = max(1, (max_points - 2) // (2 * len(metric_keys) + 2))
    selected = {0, len(items) - 1}
    for bucket in range(bucket_count):
        start = (bucket * len(items)) // bucket_count
        end = max(start + 1, ((bucket + 1) * len(items)) // bucket_count)
        selected.add(start)
        selected.add(min(len(items) - 1, end - 1))
        for key in metric_keys:
            min_idx = max_idx = None
            min_value = float('inf')
            max_value = float('-inf')
            for idx in range(start, end):
                value = (items[idx].get('measurements') or {}).get(key)
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    continue
                if value < min_value:
                    min_value, min_idx = value, idx
                if value > max_value:
                    max_value, max_idx = value, idx
            if min_idx is not None:
                selected.add(min_idx)
            if max_idx is not None:
                selected.add(max_idx)
    return [items[idx] for idx in sorted(selected)]


def parse_github_log_csv(content: str, limit: int | None = None, max_points: int = 2400) -> dict[str, Any]:
    """Parse the full CSV, return a trend-preserving sample plus the latest real rows."""
    content = (content or '').lstrip('\ufeff')
    reader = csv.DictReader(io.StringIO(content, newline=''), delimiter=';')
    if not reader.fieldnames:
        raise ValueError('CSV GIT LOG пуст или не содержит заголовка')
    columns = {str(name).strip() for name in reader.fieldnames if name}
    if not (('source_time_raw' in columns or 'event_time_utc' in columns) and
            ('ph_pc' in columns or 'ph' in columns) and
            ('temperature_c' in columns or 'tC' in columns)):
        raise ValueError('CSV GIT LOG не соответствует формату AELABS: проверьте заголовки и путь файла')

    # Canonical logger writes saturation in percent; the legacy logger used DO mg/L.
    do_units = 'pct' if 'do_sat_pct' in columns and 'do_mg_l' not in columns else 'mg_l'
    unique_rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source_row in reader:
        row = {str(k).strip(): v for k, v in source_row.items() if k is not None}
        source_time = _first(row, 'source_time_raw', 'timestamp', 'timestamp_local')
        event_time = _first(row, 'event_time_utc', 'timestamp_utc')
        if not source_time and not event_time:
            # No source timestamp means no trustworthy point.
            continue

        do_mg_l = number_cell(row.get('do_mg_l'))
        do_sat_pct = number_cell(row.get('do_sat_pct'))
        measurements = {
            'ph': number_cell(row.get('ph_pc')) if 'ph_pc' in columns else number_cell(row.get('ph')),
            'do_mg_l': do_mg_l,
            'do_sat_pct': do_sat_pct,
            'temperature_c': number_cell(row.get('temperature_c')) if 'temperature_c' in columns else number_cell(row.get('tC')),
            'rpm': number_cell(row.get('agitator_speed_rpm')) if 'agitator_speed_rpm' in columns else number_cell(row.get('rpm')),
            'microcheck_od': number_cell(row.get('od_online')) if 'od_online' in columns else number_cell(row.get('microcheck_od')),
            'od_ucheck_0_6_ae_raw': number_cell(row.get('od_ucheck_0_6_ae_raw')),
            'ph_setpoint': number_cell(row.get('ph_setpoint')),
            'agitator_setpoint_rpm': number_cell(row.get('agitator_setpoint_rpm')),
            'medium_feed_tank_mass_ae_g': number_cell(row.get('medium_feed_tank_mass_ae_g')),
            'nh4oh_bottle_mass_ae_g': number_cell(row.get('nh4oh_bottle_mass_ae_g')),
            'koh_bottle_mass_ae_g': number_cell(row.get('koh_bottle_mass_ae_g')),
        }
        # A timestamp-only/fully blank row is not a process measurement.
        plot_values = [measurements['ph'], measurements['do_mg_l'], measurements['do_sat_pct'],
                       measurements['temperature_c'], measurements['rpm'], measurements['microcheck_od']]
        if not any(value is not None for value in plot_values):
            continue

        item = {
            'source_id': _first(row, 'source_id'),
            'source_time_raw': source_time,
            'source_timezone': _first(row, 'source_timezone'),
            'event_time_utc': event_time,
            # Kept for display/debugging only; never used as the point timestamp.
            'received_at_utc': _first(row, 'received_at_utc'),
            'experiment_id': _first(row, 'experiment_id'),
            'run_id': _first(row, 'run_id'),
            'measurements': measurements,
        }
        # A repeated row caused by re-reading/re-uploading the same source sample
        # is not another reading. Exclude receive time from the identity key.
        identity = json.dumps([
            item['source_time_raw'], item['event_time_utc'], measurements,
        ], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        if identity in seen:
            continue
        seen.add(identity)
        unique_rows.append(item)

    if limit is not None:
        unique_rows = unique_rows[-max(1, int(limit)):]
    total_count = len(unique_rows)
    recent_items = unique_rows[-100:]
    trend_items = downsample_history(unique_rows, max_points=max_points)
    return {
        'items': trend_items,
        'recent_items': recent_items,
        'count': total_count,
        'trend_count': len(trend_items),
        'storage': 'github-csv',
        'do_units': do_units,
    }
