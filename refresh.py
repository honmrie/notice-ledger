"""Audit the public CanadaBuys export without treating its Open label as eligibility."""

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


SOURCE = "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"
COLUMNS = {
    "reference": "referenceNumber-numeroReference",
    "title": "title-titre-eng",
    "status": "tenderStatus-appelOffresStatut-eng",
    "closes": "tenderClosingDate-appelOffresDateCloture",
    "published": "publicationDate-datePublication",
    "amendment": "amendmentNumber-numeroModification",
    "type": "noticeType-avisType-eng",
    "buyer": "contractingEntityName-nomEntitContractante-eng",
}
MAX_BYTES = 25_000_000


def parse_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)?", value):
        raise ValueError("Invalid ISO date or timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def analyse(data, as_of):
    if len(data) > MAX_BYTES:
        raise ValueError("Source exceeds the 25 MB limit")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), strict=True)
    if not set(COLUMNS.values()).issubset(reader.fieldnames or []):
        raise ValueError("Source schema changed; stop and inspect its column names")
    records = []
    seen = set()
    counts = {"total": 0, "future": 0, "past": 0, "today": 0, "invalid_date": 0, "not_open": 0}
    for raw in reader:
        if None in raw or any(raw.get(key) is None for key in reader.fieldnames):
            raise ValueError("Malformed CSV row; no report was produced")
        item = {key: raw[column].strip() for key, column in COLUMNS.items()}
        if not item["reference"] or item["reference"] in seen:
            raise ValueError("Missing or duplicate reference; inspect the source before publishing")
        seen.add(item["reference"])
        counts["total"] += 1
        if item["status"].casefold() != "open":
            disposition = "not_open"
        else:
            try:
                closing = parse_date(item["closes"])
                disposition = "future" if closing > as_of else "past" if closing < as_of else "today"
            except ValueError:
                disposition = "invalid_date"
        counts[disposition] += 1
        item["date_screen"] = disposition
        item["eligibility"] = "Not assessed; original solicitation must be checked"
        records.append(item)
    if not records:
        raise ValueError("Empty source; no report was produced")
    assert sum(counts[key] for key in counts if key != "total") == counts["total"]
    return counts, records


def spreadsheet_safe(value):
    # CSV quoting does not prevent spreadsheet formulas from executing.
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--input", type=Path, help="Use a downloaded CSV instead of the network")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.input:
        with args.input.open("rb") as source_file:
            data = source_file.read(MAX_BYTES + 1)
        fetched_at = None
    else:
        with urlopen(Request(SOURCE, headers={"User-Agent": "NoticeLedger/0.1"}), timeout=45) as response:
            data = response.read(MAX_BYTES + 1)
        fetched_at = datetime.now(timezone.utc).isoformat()
    counts, records = analyse(data, args.as_of)
    summary = {
        "as_of_date": args.as_of.isoformat(),
        "source": SOURCE,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_fetched_at_utc": fetched_at,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "method": "Compare closing calendar dates only; do not infer a timezone. Exclude same-day and invalid dates from future candidates.",
        "scope": "Federal export only. Future date is not proof of availability or supplier eligibility.",
        "attribution": "Contains information licensed under the Open Government Licence – Canada.",
    }
    if args.output.exists():
        raise FileExistsError("Choose a new output directory to preserve the earlier snapshot")
    args.output.mkdir(parents=True)
    (args.output / "audit.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (args.output / "date-screen.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: spreadsheet_safe(value) for key, value in item.items()} for item in records)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
