#!/usr/bin/env python3
"""activity_archive.json を schema.json とつき合わせて検証する（CI から実行）。

手元で1回検証しただけだと、定例会ごとの追記で型が崩れたときに気づけない。
push のたびに走らせて、壊れたら止める。

    python .github/validate.py

★検査した件数と項目数（カナリア）を必ず表示する。0件なら検査そのものが
  空振りしているので、「エラー0件」を信用してはいけない。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

from jsonschema import Draft7Validator, FormatChecker

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "activity_archive.json"
SCHEMA = ROOT / "schema.json"


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors: list[str] = []

    # 1) スキーマ検証。format_checker を渡さないと "format": "date" は検査されない
    v = Draft7Validator(schema, format_checker=FormatChecker())
    for e in sorted(v.iter_errors(data), key=lambda e: list(e.path)):
        where = ".".join(str(x) for x in e.path) or "(全体)"
        errors.append(f"[スキーマ] {where}: {e.message}")

    # 2) 暦として実在する日付か（format:date を通っても 2026-02-30 は防げない環境がある）
    for i, r in enumerate(data):
        try:
            datetime.date.fromisoformat(r.get("date", ""))
        except ValueError:
            errors.append(f"[日付] {i}件目: date が暦として不正 → {r.get('date')!r}")

    # 3) 同じ内容の重複登録（日付＋テーマが完全に一致するもの）
    seen: dict[tuple[str, str], int] = {}
    for i, r in enumerate(data):
        k = (r.get("date", ""), r.get("question_topic", ""))
        if k in seen:
            errors.append(f"[重複] {i}件目と{seen[k]}件目が同じ (date, question_topic) → {k}")
        seen[k] = i

    n_fields = len(schema["items"]["properties"])
    print(f"検査: {len(data)}件 × {n_fields}項目 / スキーマ {SCHEMA.name}")
    filled = {k: sum(1 for r in data if r.get(k) not in ("", [], None))
              for k in schema["items"]["properties"]}
    thin = {k: n for k, n in filled.items() if n < len(data)}
    if thin:
        print("参考（中身がある件数。空欄はエラーにしない）:")
        for k, n in sorted(thin.items(), key=lambda x: x[1]):
            print(f"  {k:<16} {n:4d}/{len(data)}  ({n / len(data) * 100:4.1f}%)")
    if errors:
        print(f"\n★エラー {len(errors)}件")
        for e in errors[:50]:
            print("  " + e)
        return 1
    print("\nエラーなし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
