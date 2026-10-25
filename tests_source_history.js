'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const H = require('./static/source-history.js');

const a = {
  observation_no: 12,
  source_time_raw: '20.10.2026 14:05:10',
  event_time_utc: '2026-10-20T09:05:10Z',
  received_at_utc: '2026-10-20T09:05:14Z',
  measurements: { ph: 7.01, temperature_c: 28.4, do_mg_l: null },
};
const sameReadingFetchedLater = { ...a, received_at_utc: '2026-10-20T09:10:14Z' };
const newReading = { ...a, observation_no: 13, source_time_raw: '20.10.2026 14:05:15', event_time_utc: '2026-10-20T09:05:15Z', received_at_utc: '2026-10-20T09:05:20Z', measurements: { ...a.measurements, ph: 7.02 } };

assert.equal(H.sourceTimeLabel(a), '20.10.2026 14:05:10');
assert.equal(H.sourceTimeLabel({ received_at_utc: '2026-10-20T09:05:14Z' }), null,
  'receipt timestamp alone must not qualify as measurement time');
assert.equal(H.sourceRecordKey({ ...a, received_at_utc: 'later' }), H.sourceRecordKey(sameReadingFetchedLater),
  'fetch/receipt time changes must not create new graph points');
assert.notEqual(H.sourceRecordKey(a), H.sourceRecordKey(newReading), 'a new source reading must produce a new key');
assert.equal(H.eventTimestampMs(a), Date.parse('2026-10-20T09:05:10Z'), 'source event UTC is canonical for freshness');
assert.equal(H.eventTimestampMs({ source_time_raw: a.source_time_raw, received_at_utc: a.received_at_utc }), null,
  'never use received time for source freshness');
assert.ok(Number.isFinite(H.sourceTimestampMs(a)), 'source timestamp should be parsed');
assert.ok(Number.isFinite(H.sourceTimestampMs({ source_time_raw: '20.10.2026 14:05:10' })), 'localized DD.MM.YYYY source time should be parsed');
assert.equal(H.eventTimestampMs({ source_time_raw: '20.10.2026 14:05:10' }), null, 'timezone-free local source time must not be compared to browser UTC');
assert.equal(H.eventTimestampMs({ source_time_raw: '2026-10-20T09:05:10Z' }), Date.parse('2026-10-20T09:05:10Z'));
assert.equal(H.sourceTimestampMs({ source_time_raw: 'bad timestamp', received_at_utc: a.received_at_utc }), null,
  'unparseable source time must not fall back to received time');
const html = fs.readFileSync(require('node:path').join(__dirname, 'static', 'index.html'), 'utf8');
assert.ok(!html.includes('client_sample_ms'), 'browser polling timestamps must not be stored as measurement times');
assert.ok(!html.includes('received_at_utc||'), 'receipt time must not be used as a trend fallback');
assert.ok(html.includes('MAX_TREND_GAP_MS=30000'), 'large source-time gaps must be represented as line breaks');
assert.ok(html.includes('setValIfReadable'), 'empty sensor fields should preserve last readable values');
console.log('source-history tests passed');
