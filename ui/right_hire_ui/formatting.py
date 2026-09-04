"""Pure display helpers shared by the Results view. No Reflex, no I/O — run this
file directly (`python ui/right_hire_ui/formatting.py`) for its self-check."""

from __future__ import annotations

import csv
import io

SHORTLIST_VERDICTS = ("Fit", "Maybe")
SHORTLIST_COLUMNS = [
    "Name",
    "Email",
    "Score",
    "Category",
    "Experience",
    "Location",
    "Missing Skills",
]


def bucket_tone(bucket: str, fit: float, maybe: float) -> str:
    """Which verdict band a histogram bucket ("0.6–0.7") falls in, judged by its
    midpoint — a bucket straddling a threshold is shown honestly by the dashed
    threshold line drawn over the chart."""
    lo, _, hi = bucket.partition("–")
    try:
        mid = round((float(lo) + float(hi)) / 2, 6)  # binary float: 0.6+0.7 lands at 0.6499…
    except ValueError:
        return "reject"
    if mid >= fit:
        return "fit"
    if mid >= maybe:
        return "maybe"
    return "reject"


def shortlist_csv(rows: list[dict]) -> str:
    """CSV of the Fit + Maybe candidates, in the order the queue shows them."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SHORTLIST_COLUMNS)
    for r in rows:
        if r.get("verdict") not in SHORTLIST_VERDICTS:
            continue
        writer.writerow(
            [
                r.get("name", ""),
                r.get("email", ""),
                r.get("score_display", ""),
                r.get("verdict", ""),
                r.get("yoe", ""),
                r.get("location", ""),
                ", ".join(r.get("missing_skills") or []),
            ]
        )
    return buf.getvalue()


def _demo() -> None:
    assert bucket_tone("0.9–1.0", 0.7, 0.4) == "fit"
    assert bucket_tone("0.6–0.7", 0.7, 0.4) == "maybe"  # mid 0.65 < fit
    assert bucket_tone("0.6–0.7", 0.65, 0.4) == "fit"  # mid 0.65 >= fit
    assert bucket_tone("0.3–0.4", 0.7, 0.4) == "reject"
    assert bucket_tone("junk", 0.7, 0.4) == "reject"

    rows = [
        {
            "name": "A",
            "email": "a@x.com",
            "score_display": "0.82",
            "verdict": "Fit",
            "yoe": "5",
            "location": "Tokyo",
            "missing_skills": ["Go", "K8s"],
        },
        {"name": "B", "verdict": "Reject", "score_display": "0.10"},
        {"name": "C", "verdict": "Maybe", "score_display": "0.52", "missing_skills": []},
    ]
    out = shortlist_csv(rows).splitlines()
    assert out[0].startswith("Name,Email,Score")
    assert len(out) == 3, out  # header + Fit + Maybe, Reject dropped
    assert '"Go, K8s"' in out[1]
    assert out[2].startswith("C,,0.52,Maybe")
    print("formatting self-check OK")


if __name__ == "__main__":
    _demo()
