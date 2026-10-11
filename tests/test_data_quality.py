import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class Contracts(unittest.TestCase):
    def test_title_and_identity(self):
        from etl.data_quality import parse_title, rating_event_id
        self.assertEqual(parse_title('Film (1999)'), ('Film', 1999))
        self.assertEqual(parse_title('Film (1999) extended'), ('Film (1999) extended', None))
        self.assertEqual(rating_event_id(1, 2, 3), rating_event_id(1, 2, 3))
        self.assertNotEqual(rating_event_id(1, 2, 3), rating_event_id(1, 2, 4))

    def test_scd_field_independence_and_nulls(self):
        from etl.data_quality import scd3
        first = scd3({}, {'runtime': 90, 'original_language': 'en'}, 'A')
        self.assertIsNone(first['previous_runtime'])
        changed = scd3(first, {'runtime': 95, 'original_language': 'en'}, 'C')
        self.assertEqual(changed['previous_runtime'], 90)
        self.assertIsNone(changed['previous_original_language'])
        self.assertEqual(scd3(changed, {'runtime': 95, 'original_language': 'en'}, 'D'), changed)
        self.assertEqual(scd3(changed, None, 'E'), changed)

    def test_atomic_json(self):
        from utils.common import atomic_json, read_json
        with TemporaryDirectory() as d:
            p = Path(d) / 'state.json'
            atomic_json(p, {'status': 'ok'})
            self.assertEqual(read_json(p), {'status': 'ok'})


if __name__ == '__main__':
    unittest.main()


import csv
from etl.extract import audit


def test_optional_hyphenated_genome_files_are_audited(cfg):
    from pathlib import Path
    root=Path(cfg['paths']['raw_movielens'])
    (root/'genome-tags.csv').write_text('tagId,tag\n1,science fiction\n')
    (root/'genome-scores.csv').write_text('movieId,tagId,relevance\n1,1,0.5\n')
    result=audit(cfg)
    assert result['files']['genome-tags']['rows']==1
    assert result['files']['genome-scores']['rows']==1


def test_malformed_csv_is_counted_not_silently_skipped(cfg):
    from pathlib import Path
    with (Path(cfg['paths']['raw_movielens'])/'ratings.csv').open('a') as f:
        f.write('1,2,3.0,1000000005,extra\n')
    result=audit(cfg)
    assert result['files']['ratings']['rows']==1805
    assert result['files']['ratings']['malformed_rows']==1


def test_quoted_titles_keep_embedded_commas_and_quotes(cfg):
    from pathlib import Path
    with (Path(cfg['paths']['raw_movielens'])/'movies.csv').open('a') as f:
        f.write('31,"A, ""B"" (2000)",Drama\n')
    result=audit(cfg)
    assert result['files']['movies']['rows']==31
    assert result['files']['movies']['malformed_rows']==0

