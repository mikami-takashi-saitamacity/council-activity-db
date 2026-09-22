#!/usr/bin/env python3
"""activity_archive.json と schema.json から stats.json と README の件数表示を決定的に生成する。

    python scripts/build_stats.py          # stats.json と README の生成ブロックを書き換える
    python scripts/build_stats.py --check  # 書き換えず、正本の生成結果と一致するか確認する（CI用）

result_level・source_type のキー一覧は schema.json の enum をそのまま使う。
ここで別に定義し直さない（schema 改訂のたびに二重管理になるため）。
未知の enum 値（schema にない値）があれば、黙って落とさず FAIL する。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "activity_archive.json"
SCHEMA_PATH = ROOT / "schema.json"
STATS_PATH = ROOT / "stats.json"
README_PATH = ROOT / "README.md"

BLOCK_START = "<!-- stats:start -->"
BLOCK_END = "<!-- stats:end -->"


def load_data(data_path: pathlib.Path = DATA_PATH, schema_path: pathlib.Path = SCHEMA_PATH) -> tuple[list[dict], dict]:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return data, schema


def compute_stats(data: list[dict], schema: dict) -> dict:
    props = schema["items"]["properties"]
    source_type_enum = props["source_type"]["enum"]
    result_level_enum = props["result_level"]["enum"]

    # dict のキー順は enum の順（schema.json 側の並びが正）。sort_keys はしない。
    by_source_type = {k: 0 for k in source_type_enum}
    by_result_level = {k: 0 for k in result_level_enum}

    for i, record in enumerate(data):
        st = record.get("source_type")
        if st not in by_source_type:
            raise ValueError(f"{i}件目: 未知の source_type {st!r}（schema.json の enum に存在しない）")
        by_source_type[st] += 1

        rl = record.get("result_level")
        if rl not in by_result_level:
            raise ValueError(f"{i}件目: 未知の result_level {rl!r}（schema.json の enum に存在しない）")
        by_result_level[rl] += 1

    return {
        "total": len(data),
        "by_source_type": by_source_type,
        "by_result_level": by_result_level,
    }


def render_stats_json(stats: dict) -> str:
    # 現在時刻など、実行のたびに変わる値は一切含めない。UTF-8・escape最小限。
    return json.dumps(stats, ensure_ascii=False, indent=2) + "\n"


def render_readme_block(stats: dict) -> str:
    # schema enum → 集計辞書 → stats.json → README生成ブロック、の一方向。
    # 分類名の一覧をここで別に固定記述しない（compute_stats が schema enum から
    # 作った辞書をそのまま順に描画するだけ）。schema に分類が増えれば、この関数を
    # 直さなくても stats.json・README の両方に自動的に反映される。
    total = stats["total"]
    st_text = "／".join(f"{name}{count}件" for name, count in stats["by_source_type"].items())
    rl_text = "／".join(f"{name}{count}件" for name, count in stats["by_result_level"].items())
    lines = [
        BLOCK_START,
        f"- 収録件数：{total}件（定例会ごとに追加予定）",
        f"- 種別：{st_text}",
        "- 分野タグ：15分類（複数付与あり）",
        f"- 対応状況：{rl_text}",
        BLOCK_END,
    ]
    return "\n".join(lines)


class ReadmeMarkerError(ValueError):
    """README.md の stats:start/end マーカーが1個ずつ・正順で存在しない場合。"""


def apply_readme_block(readme_text: str, block: str) -> str:
    start_count = readme_text.count(BLOCK_START)
    end_count = readme_text.count(BLOCK_END)

    if start_count == 0:
        raise ReadmeMarkerError(f"README.md に {BLOCK_START} が見つかりません。生成範囲が特定できないため書き換えません。")
    if end_count == 0:
        raise ReadmeMarkerError(f"README.md に {BLOCK_END} が見つかりません。生成範囲が特定できないため書き換えません。")
    if start_count > 1:
        raise ReadmeMarkerError(f"README.md に {BLOCK_START} が{start_count}個あります（1個である必要があります）。書き換えません。")
    if end_count > 1:
        raise ReadmeMarkerError(f"README.md に {BLOCK_END} が{end_count}個あります（1個である必要があります）。書き換えません。")

    start = readme_text.find(BLOCK_START)
    end = readme_text.find(BLOCK_END)
    if end < start:
        raise ReadmeMarkerError(f"README.md で {BLOCK_END} が {BLOCK_START} より前にあります。書き換えません。")

    end += len(BLOCK_END)
    return readme_text[:start] + block + readme_text[end:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="書き換えず、正本との一致だけを確認する")
    args = parser.parse_args()

    data, schema = load_data()
    stats = compute_stats(data, schema)
    stats_json = render_stats_json(stats)
    readme_block = render_readme_block(stats)

    readme_text = README_PATH.read_text(encoding="utf-8")
    try:
        new_readme_text = apply_readme_block(readme_text, readme_block)
    except ReadmeMarkerError as e:
        print(f"NG: {e}")
        return 1

    if args.check:
        problems = []
        current_stats_json = STATS_PATH.read_text(encoding="utf-8") if STATS_PATH.exists() else None
        if current_stats_json != stats_json:
            problems.append(f"{STATS_PATH.name} が正本から生成される内容と一致しません")
        if readme_text != new_readme_text:
            problems.append("README.md の stats 生成ブロックが正本から生成される内容と一致しません")
        if problems:
            print("NG:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"OK: stats.json / README生成ブロックは正本と一致（total={stats['total']}）")
        return 0

    STATS_PATH.write_text(stats_json, encoding="utf-8")
    README_PATH.write_text(new_readme_text, encoding="utf-8")
    print(f"更新しました: {STATS_PATH.name}, README.md の stats ブロック（total={stats['total']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
