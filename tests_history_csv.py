import unittest
from history_csv import parse_github_log_csv

CANONICAL_HEADER = ';'.join([
    'source_id','source_time_raw','source_timezone','event_time_utc','received_at_utc',
    'experiment_id','run_id','od_online','medium_feed_tank_mass_ae_g','nh4oh_bottle_mass_ae_g',
    'koh_bottle_mass_ae_g','od_ucheck_0_6_ae_raw','ph_pc','ph_setpoint','temperature_c',
    'do_sat_pct','agitator_speed_rpm','agitator_setpoint_rpm'
])

def csv_row(source_time, event_time, received_time, ph='7,05', temp='24,50', do='80,00', rpm='600,00', od='16,123456'):
    # source_time is written in the exact Excel-text style from the desktop CSV.
    return ';'.join([
        'DS-01.01', f'="{source_time}"', 'Asia/Yekaterinburg', event_time,
        f'="{received_time}"', 'exp-1', 'run-1', od, '1200,00', '250,00', '300,00',
        '16,123456', ph, '7,00', temp, do, rpm, '600,00'
    ])

class GithubLogCsvTests(unittest.TestCase):
    def test_reads_exact_source_time_and_decimal_comma(self):
        content='\ufeff'+CANONICAL_HEADER+'\n'+csv_row('20.10.2026 14:05:10','2026-10-20T09:05:10Z','2026-10-20T09:05:14Z')
        got=parse_github_log_csv(content)
        self.assertEqual(got['storage'],'github-csv')
        self.assertEqual(got['do_units'],'pct')
        self.assertEqual(got['count'],1)
        self.assertEqual(got['items'][0]['source_time_raw'],'20.10.2026 14:05:10')
        self.assertEqual(got['items'][0]['event_time_utc'],'2026-10-20T09:05:10Z')
        self.assertEqual(got['items'][0]['measurements']['ph'],7.05)
        self.assertAlmostEqual(got['items'][0]['measurements']['microcheck_od'],16.123456)

    def test_duplicate_rows_different_receive_time_are_collapsed(self):
        row1=csv_row('20.10.2026 14:05:10','2026-10-20T09:05:10Z','2026-10-20T09:05:14Z')
        row2=csv_row('20.10.2026 14:05:10','2026-10-20T09:05:10Z','2026-10-20T09:05:19Z')
        got=parse_github_log_csv(CANONICAL_HEADER+'\n'+row1+'\n'+row2)
        self.assertEqual(got['count'],1)

    def test_new_timestamp_creates_a_new_point(self):
        row1=csv_row('20.10.2026 14:05:10','2026-10-20T09:05:10Z','2026-10-20T09:05:14Z')
        row2=csv_row('20.10.2026 14:05:15','2026-10-20T09:05:15Z','2026-10-20T09:05:19Z',ph='7,06')
        got=parse_github_log_csv(CANONICAL_HEADER+'\n'+row1+'\n'+row2)
        self.assertEqual(got['count'],2)
        self.assertEqual(got['items'][-1]['measurements']['ph'],7.06)

    def test_timestamp_only_or_blank_data_row_is_not_a_point(self):
        blank=csv_row('20.10.2026 14:05:10','2026-10-20T09:05:10Z','2026-10-20T09:05:14Z',ph='',temp='',do='',rpm='',od='')
        got=parse_github_log_csv(CANONICAL_HEADER+'\n'+blank)
        self.assertEqual(got['count'],0)

    def test_missing_source_time_is_not_filled_from_received_time(self):
        content=CANONICAL_HEADER+'\n'+';'.join(['DS-01.01','','Asia/Yekaterinburg','','="2026-10-20T09:05:14Z"','exp-1','run-1','16,123456','1200,00','250,00','300,00','16,123456','7,05','7,00','24,50','80,00','600,00','600,00'])
        got=parse_github_log_csv(content)
        self.assertEqual(got['count'],0)

    def test_legacy_csv_maps_do_mg_l(self):
        header='event_time_utc;received_at_utc;source_time_raw;source_timezone;observation_no;source_id;experiment_id;run_id;ph;temperature_c;do_mg_l;rpm;offgas_do_pct;microcheck_od'
        row='2026-10-20T09:05:10Z;2026-10-20T09:05:14Z;="20.10.2026 14:05:10";Asia/Yekaterinburg;12;DS-01.01;exp-1;run-1;7,05;24,50;6,30;600;8,00;16,123456'
        got=parse_github_log_csv(header+'\n'+row)
        self.assertEqual(got['do_units'],'mg_l')
        self.assertEqual(got['items'][0]['measurements']['do_mg_l'],6.3)

if __name__=='__main__':
    unittest.main()
