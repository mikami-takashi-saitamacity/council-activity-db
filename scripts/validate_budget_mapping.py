#!/usr/bin/env python3
"""手順8: 既存予算提案324件と正本マスターの対応表を検証する。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "activity_archive.json"
MASTER_PATH = ROOT / "budget_master.json"
MAPPING_PATH = ROOT / "budget_existing_mapping.json"
UNMATCHED_PATH = ROOT / "budget_unmatched_master.json"


class MappingValidationError(Exception):
    pass


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def validate(archive, master, mapping, unmatched):
    if not isinstance(archive, list) or not isinstance(master, list):
        raise MappingValidationError("archive/master must be arrays")
    if not isinstance(mapping, dict) or not isinstance(mapping.get("entries"), list):
        raise MappingValidationError("mapping.entries must be an array")
    if not isinstance(unmatched, dict) or not isinstance(unmatched.get("items"), list):
        raise MappingValidationError("unmatched.items must be an array")

    budget_indices = [i for i, r in enumerate(archive) if r.get("source_type") == "予算提案"]
    entries = mapping["entries"]

    if len(entries) != len(budget_indices):
        raise MappingValidationError(
            f"mapping entry count mismatch: {len(entries)} != {len(budget_indices)}"
        )

    seen_indices = set()
    master_by_locator = {r["source_locator"]: r for r in master}
    if len(master_by_locator) != len(master):
        raise MappingValidationError("budget_master source_locator is not unique")

    covered_by = {}
    for entry in entries:
        idx = entry.get("archive_index")
        if not isinstance(idx, int) or not (0 <= idx < len(archive)):
            raise MappingValidationError(f"invalid archive_index: {idx!r}")
        if idx in seen_indices:
            raise MappingValidationError(f"duplicate archive_index: {idx}")
        seen_indices.add(idx)

        record = archive[idx]
        if record.get("source_type") != "予算提案":
            raise MappingValidationError(f"archive_index {idx} is not a budget record")

        for key in ("date", "session_name", "question_topic", "proposal"):
            if entry.get(key) != record.get(key):
                raise MappingValidationError(
                    f"archive_index {idx}: fingerprint mismatch for {key}"
                )

        locators = entry.get("source_locators")
        if not isinstance(locators, list) or not locators:
            raise MappingValidationError(f"archive_index {idx}: source_locators is empty")
        if len(locators) != len(set(locators)):
            raise MappingValidationError(f"archive_index {idx}: duplicate locator within entry")

        expected_type = "one_to_one" if len(locators) == 1 else "one_to_many"
        if entry.get("mapping_type") != expected_type:
            raise MappingValidationError(
                f"archive_index {idx}: mapping_type mismatch"
            )

        record_year = int(record["date"][:4])
        for loc in locators:
            if loc not in master_by_locator:
                raise MappingValidationError(
                    f"archive_index {idx}: unknown source_locator {loc}"
                )
            if master_by_locator[loc]["fiscal_year"] != record_year:
                raise MappingValidationError(
                    f"archive_index {idx}: fiscal year mismatch for {loc}"
                )
            if loc in covered_by:
                raise MappingValidationError(
                    f"source_locator {loc} mapped by multiple old records: "
                    f"{covered_by[loc]} and {idx}"
                )
            covered_by[loc] = idx

    if seen_indices != set(budget_indices):
        missing = sorted(set(budget_indices) - seen_indices)
        extra = sorted(seen_indices - set(budget_indices))
        raise MappingValidationError(
            f"budget record coverage mismatch: missing={missing}, extra={extra}"
        )

    expected_unmatched = [r for r in master if r["source_locator"] not in covered_by]
    if unmatched["items"] != expected_unmatched:
        raise MappingValidationError("budget_unmatched_master.json is not the exact master-minus-covered set")

    computed = {
        "activity_archive_total": len(archive),
        "existing_budget_records": len(budget_indices),
        "authoritative_master_items": len(master),
        "covered_master_items": len(covered_by),
        "unmatched_master_items": len(expected_unmatched),
    }
    for key, value in computed.items():
        if mapping.get(key) != value:
            raise MappingValidationError(
                f"mapping metadata mismatch for {key}: {mapping.get(key)!r} != {value!r}"
            )
    if unmatched.get("count") != len(expected_unmatched):
        raise MappingValidationError("unmatched count metadata mismatch")

    by_year = {}
    for year in sorted({r["fiscal_year"] for r in master}):
        old_count = sum(1 for i in budget_indices if int(archive[i]["date"][:4]) == year)
        covered_count = sum(
            1 for loc in covered_by if master_by_locator[loc]["fiscal_year"] == year
        )
        master_count = sum(1 for r in master if r["fiscal_year"] == year)
        by_year[str(year)] = {
            "old_records": old_count,
            "covered_master_items": covered_count,
            "unmatched_master_items": master_count - covered_count,
        }

    return {
        **computed,
        "one_to_one_records": sum(1 for e in entries if e["mapping_type"] == "one_to_one"),
        "one_to_many_records": sum(1 for e in entries if e["mapping_type"] == "one_to_many"),
        "by_year": by_year,
    }


def main() -> int:
    try:
        summary = validate(
            load_json(ARCHIVE_PATH),
            load_json(MASTER_PATH),
            load_json(MAPPING_PATH),
            load_json(UNMATCHED_PATH),
        )
    except (OSError, json.JSONDecodeError, MappingValidationError) as e:
        print(f"NG: {e}")
        return 1

    print("OK: budget step8 mapping is internally consistent")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
