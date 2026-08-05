from __future__ import annotations

from app.pipeline.ingest import parse_csv


def test_parse_csv_basic():
    csv_bytes = (
        b"Full Name,Email Address,Years of Experience,City,Resume Link\n"
        b"Alice,alice@test.com,5,SF,http://example.com/a.pdf\n"
        b"Bob,bob@test.com,2,NY,http://example.com/b.pdf\n"
    )
    rows = parse_csv(csv_bytes)
    assert len(rows) == 2
    assert rows[0] == {
        "name": "Alice",
        "email": "alice@test.com",
        "yoe": "5",
        "location": "SF",
        "resume_url": "http://example.com/a.pdf",
    }


def test_parse_csv_skips_blank_rows():
    csv_bytes = b"name,email\nAlice,alice@test.com\n,\nBob,bob@test.com\n"
    rows = parse_csv(csv_bytes)
    assert len(rows) == 2
    assert [r["name"] for r in rows] == ["Alice", "Bob"]


def test_parse_csv_empty_file_returns_empty_list():
    assert parse_csv(b"") == []


def test_parse_csv_handles_utf8_bom():
    csv_bytes = b"\xef\xbb\xbfname,email\nAlice,alice@test.com\n"
    rows = parse_csv(csv_bytes)
    assert rows == [{"name": "Alice", "email": "alice@test.com"}]
