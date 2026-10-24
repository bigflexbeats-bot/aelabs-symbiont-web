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


def _first_number(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = number_cell(row.get(name))
        if value is not None:
            return value
    return None


def parse_github_log_csv(content: str, limit: int = 500) -> dict[str, Any]:
    """Parse canonical semicolon CSV and return the latest unique source rows."""
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
            'offgas_o2_online_ae_pct': number_cell(row.get('offgas_o2_online_ae_pct')),
            'offgas_ch4_online_ae_pct': number_cell(row.get('offgas_ch4_online_ae_pct')),
            'offgas_co2_online_ae_pct': number_cell(row.get('offgas_co2_online_ae_pct')),
            # airflow_pr100 / air_flow_online_ae_nl_min — прежние имена того же столбца.
            'air_flow_online_ae_l_min': _first_number(row, 'air_flow_online_ae_l_min', 'air_flow_online_ae_nl_min', 'airflow_pr100'),
            'o2_flow_online_ae_l_min': _first_number(row, 'o2_flow_online_ae_l_min'),
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

    items = unique_rows[-max(1, int(limit)):]
    return {
        'items': items,
        'count': len(items),
        'storage': 'github-csv',
        'do_units': do_units,
    }
