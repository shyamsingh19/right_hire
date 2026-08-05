#!/usr/bin/env python
"""Evaluate pipeline accuracy against a labeled CSV.

CSV format: candidate_id,expected_verdict
Verdicts: Fit, Maybe, Reject
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Evaluation


async def _load_evaluations(candidate_ids: list[str]) -> dict[str, str]:
    engine = create_async_engine(settings.async_database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        result = await session.execute(
            select(Evaluation.candidate_id, Evaluation.verdict).where(
                Evaluation.candidate_id.in_(candidate_ids)
            )
        )
        rows = result.fetchall()

    await engine.dispose()
    return {row[0]: row[1] for row in rows}


def precision_at_k(predictions: list[str], labels: list[str], target: str, k: int) -> float:
    """Precision of the top-k predicted positives for a given class."""
    paired = list(zip(predictions, labels))
    predicted_positive = [p for p in paired if p[0] == target][:k]
    if not predicted_positive:
        return 0.0
    correct = sum(1 for pred, label in predicted_positive if label == target)
    return correct / len(predicted_positive)


async def main(csv_path: str, k: int) -> None:
    labeled: list[tuple[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            labeled.append((row["candidate_id"], row["expected_verdict"]))

    if not labeled:
        print("No labeled rows found in CSV.")
        sys.exit(1)

    candidate_ids = [cid for cid, _ in labeled]
    predictions = await _load_evaluations(candidate_ids)

    total = len(labeled)
    correct = 0
    missing = 0
    for cid, expected in labeled:
        predicted = predictions.get(cid)
        if predicted is None:
            missing += 1
            continue
        if predicted == expected:
            correct += 1

    accuracy = correct / (total - missing) if (total - missing) > 0 else 0.0

    pred_list = [predictions.get(cid, "Unknown") for cid, _ in labeled]
    label_list = [lbl for _, lbl in labeled]

    print(f"Total labeled: {total}  |  Evaluated: {total - missing}  |  Missing: {missing}")
    print(f"Accuracy: {accuracy:.2%}")
    for verdict in ("Fit", "Maybe", "Reject"):
        p = precision_at_k(pred_list, label_list, verdict, k)
        print(f"Precision@{k} ({verdict}): {p:.2%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate pipeline against labeled set")
    parser.add_argument("csv", help="Path to CSV with candidate_id,expected_verdict columns")
    parser.add_argument("--k", type=int, default=10, help="K for precision@k (default: 10)")
    args = parser.parse_args()
    asyncio.run(main(args.csv, args.k))
