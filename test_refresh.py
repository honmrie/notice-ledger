import csv
from datetime import date
import io
import unittest

from refresh import COLUMNS, analyse, spreadsheet_safe


def fixture(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(COLUMNS.values()))
    writer.writeheader()
    for index, overrides in enumerate(rows):
        row = {field: "" for field in COLUMNS.values()}
        row.update({COLUMNS["reference"]: str(index), COLUMNS["status"]: "Open", COLUMNS["title"]: 'Title, with "quotes"\nand newline'})
        row.update({COLUMNS[key]: value for key, value in overrides.items()})
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


class AuditTests(unittest.TestCase):
    def test_date_screen_and_multiline_csv(self):
        data = fixture([
            {"closes": "2026-10-19T14:00:00"},
            {"closes": "2026-10-17T14:00:00"},
            {"closes": "2026-10-18T23:59:00"},
            {"closes": "2026-02-30"},
            {"closes": "2026-10-20", "status": "Cancelled"},
        ])
        counts, records = analyse(data, date(2026, 10, 18))
        self.assertEqual(counts, {"total": 5, "future": 1, "past": 1, "today": 1, "invalid_date": 1, "not_open": 1})
        self.assertIn('\n', records[0]["title"])

    def test_fail_closed_on_schema_or_duplicate(self):
        for data in (b"name\nwrong\n", fixture([]), fixture([{"reference": "same"}, {"reference": "same"}])):
            with self.assertRaises(ValueError):
                analyse(data, date(2026, 10, 18))

    def test_formula_injection(self):
        for value in ("=1+1", "  +CMD", "-1+2", "@SUM(1)", "\ttext"):
            self.assertTrue(spreadsheet_safe(value).startswith("'"))
        self.assertEqual(spreadsheet_safe("ordinary title"), "ordinary title")


if __name__ == "__main__":
    unittest.main()
