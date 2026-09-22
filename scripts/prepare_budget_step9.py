#!/usr/bin/env python3
"""v1.2.0 手順9用の非公開レビュー候補を生成する。

公開DB(activity_archive.json)は変更しない。
result_level は公開schemaで必須かつ三神本人の判定項目なので、未判定の
欠落293件・分割対象を仮値で公開DBへ入れない。

出力はローカル作業用ディレクトリ（既定: _budget_review/）に置き、
Gitにはcommitしない。

    python scripts/prepare_budget_step9.py
    python scripts/prepare_budget_step9.py --check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "activity_archive.json"
MASTER = ROOT / "budget_master.json"
MAPPING = ROOT / "budget_existing_mapping.json"
DEFAULT_OUTPUT = ROOT / "_budget_review" / "budget_step9_candidates.json"

EXPECTED = {
    "master_items": 625,
    "existing_budget_records": 324,
    "covered_master_items": 332,
    "existing_1to1": 317,
    "split_candidates": 15,
    "missing_candidates": 293,
}

FINGERPRINT_FIELDS = ("date", "session_name", "question_topic", "proposal")


class Step9Error(Exception):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise Step9Error(f"{path}: {e}") from e


def build_candidates(archive: list[dict], master: list[dict], mapping: dict) -> dict:
    if len(master) != EXPECTED["master_items"]:
        raise Step9Error(f"budget_master件数が想定外: {len(master)}")
    locators = [m.get("source_locator") for m in master]
    if len(locators) != len(set(locators)):
        raise Step9Error("budget_masterのsource_locatorが重複しています")

    entries = mapping.get("entries")
    if not isinstance(entries, list):
        raise Step9Error("budget_existing_mapping.json の entries が配列ではありません")
    if len(entries) != EXPECTED["existing_budget_records"]:
        raise Step9Error(f"mapping entry件数が想定外: {len(entries)}")

    master_by_locator = {m["source_locator"]: m for m in master}
    locator_to_entry: dict[str, dict] = {}
    seen_archive_indices: set[int] = set()

    for entry in entries:
        idx = entry.get("archive_index")
        if not isinstance(idx, int) or not (0 <= idx < len(archive)):
            raise Step9Error(f"不正なarchive_index: {idx!r}")
        if idx in seen_archive_indices:
            raise Step9Error(f"archive_index重複: {idx}")
        seen_archive_indices.add(idx)

        old = archive[idx]
        if old.get("source_type") != "予算提案":
            raise Step9Error(f"archive_index {idx} は予算提案ではありません")
        for field in FINGERPRINT_FIELDS:
            if entry.get(field) != old.get(field):
                raise Step9Error(f"archive_index {idx}: {field} fingerprint不一致")

        mapped = entry.get("source_locators")
        if not isinstance(mapped, list) or not mapped:
            raise Step9Error(f"archive_index {idx}: source_locatorsが空です")
        for loc in mapped:
            if loc not in master_by_locator:
                raise Step9Error(f"未知のsource_locator: {loc}")
            if loc in locator_to_entry:
                raise Step9Error(f"source_locatorが複数旧レコードに対応: {loc}")
            locator_to_entry[loc] = entry

    if len(locator_to_entry) != EXPECTED["covered_master_items"]:
        raise Step9Error(f"対応済み正本項目数が想定外: {len(locator_to_entry)}")

    candidates = []
    for m in master:
        loc = m["source_locator"]
        entry = locator_to_entry.get(loc)

        if entry is None:
            status = "missing"
            legacy_index = None
            legacy_record = None
            inheritance = "none"
        else:
            legacy_index = entry["archive_index"]
            legacy_record = archive[legacy_index]
            if len(entry["source_locators"]) == 1:
                status = "existing_1to1"
                inheritance = "carryover_requires_confirmation"
            else:
                status = "split_from_existing"
                inheritance = "do_not_inherit_result_level_without_review"

        candidate = {
            "fiscal_year": m["fiscal_year"],
            "source_locator": loc,
            "major_no": m["major_no"],
            "major_title": m["major_title"],
            "item_no": m["item_no"],
            "proposal_text": m["proposal_text"],
            "candidate_status": status,
            "review_status": "pending",
            "legacy_archive_index": legacy_index,
            "inheritance_policy": inheritance,
            "legacy_record": legacy_record,
        }
        candidates.append(candidate)

    counts = {
        "master_items": len(candidates),
        "existing_budget_records": len(entries),
        "covered_master_items": len(locator_to_entry),
        "existing_1to1": sum(c["candidate_status"] == "existing_1to1" for c in candidates),
        "split_candidates": sum(c["candidate_status"] == "split_from_existing" for c in candidates),
        "missing_candidates": sum(c["candidate_status"] == "missing" for c in candidates),
    }
    if counts != EXPECTED:
        raise Step9Error(f"候補件数audit不一致: actual={counts}, expected={EXPECTED}")

    # 公開用フィールドに未判定値を捏造しない。result_level/tags等は
    # legacy_record内に参考情報として存在し得るが、candidate直下には置かない。
    forbidden_top = {"result_level", "tags", "question_topic", "summary", "answer_summary", "date", "id"}
    for c in candidates:
        leaked = forbidden_top & set(c)
        if leaked:
            raise Step9Error(f"{c['source_locator']}: 未確定公開フィールドがcandidate直下に存在: {sorted(leaked)}")

    return {
        "version": "1.0",
        "purpose": "v1.2.0 step9 private review candidates; do not publish before step10 review",
        "counts": counts,
        "candidates": candidates,
    }


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--check", action="store_true", help="既存出力と再生成結果が一致するか確認")
    args = p.parse_args()

    try:
        data = build_candidates(load_json(ARCHIVE), load_json(MASTER), load_json(MAPPING))
    except Step9Error as e:
        print(f"NG: {e}")
        return 1

    expected = render(data)
    if args.check:
        if not args.output.exists():
            print(f"NG: {args.output} がありません")
            return 1
        actual = args.output.read_text(encoding="utf-8")
        if actual != expected:
            print(f"NG: {args.output} が再生成結果と一致しません")
            return 1
        print(f"OK: step9 candidates一致 ({data['counts']})")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    print(f"generated: {args.output}")
    print(json.dumps(data["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
