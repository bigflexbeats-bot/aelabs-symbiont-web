/* Source-time helpers shared by AELABS WEB and its offline tests.
 * These functions deliberately never fall back to server/browser receipt time.
 */
(function (root) {
  'use strict';

  function sourceTimeLabel(item) {
    if (!item || typeof item !== 'object') return null;
    const raw = typeof item.source_time_raw === 'string' ? item.source_time_raw.trim() : '';
    if (raw) return raw;
    const event = typeof item.event_time_utc === 'string' ? item.event_time_utc.trim() : '';
    return event || null;
  }

  function parseRawSourceTime(raw) {
    if (typeof raw !== 'string' || !raw.trim()) return null;
    const value = raw.trim();
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
    // Desktop's Russian locale may write DD.MM.YYYY HH:mm:ss.
    const m = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})[ T,]+(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,3}))?)?$/.exec(value);
    if (!m) return null;
    const ms = Number((m[7] || '0').padEnd(3, '0').slice(0, 3));
    const date = new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]), Number(m[4]), Number(m[5]), Number(m[6] || 0), ms);
    const ts = date.getTime();
    return Number.isFinite(ts) ? ts : null;
  }

  function sourceTimestampMs(item) {
    if (!item || typeof item !== 'object') return null;
    const event = typeof item.event_time_utc === 'string' ? item.event_time_utc.trim() : '';
    if (event) {
      const parsed = Date.parse(event);
      if (Number.isFinite(parsed)) return parsed;
    }
    return parseRawSourceTime(item.source_time_raw);
  }

  function eventTimestampMs(item) {
    if (!item || typeof item !== 'object') return null;
    const event = typeof item.event_time_utc === 'string' ? item.event_time_utc.trim() : '';
    if (event) {
      const parsed = Date.parse(event);
      if (Number.isFinite(parsed)) return parsed;
    }
    // A raw source timestamp with an explicit UTC offset is also safe for age checks.
    // Do not compare timezone-free local timestamps to the browser's timezone.
    const raw = typeof item.source_time_raw === 'string' ? item.source_time_raw.trim() : '';
    if (/T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)) {
      const parsed = Date.parse(raw);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  }

  function sourceRecordKey(item) {
    if (!sourceTimeLabel(item)) return null;
    const measurements = item.measurements && typeof item.measurements === 'object' ? item.measurements : {};
    const canonicalMeasurements = Object.keys(measurements).sort().map((key) => [key, measurements[key]]);
    // received_at_utc is purposefully excluded: it changes when files are fetched/published,
    // and does not prove that the measurement itself is new.
    return JSON.stringify([
      item.observation_no ?? null,
      item.event_time_utc || null,
      item.source_time_raw || null,
      canonicalMeasurements,
    ]);
  }

  const api = { sourceTimeLabel, parseRawSourceTime, sourceTimestampMs, eventTimestampMs, sourceRecordKey };
  root.AELABSHistory = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
