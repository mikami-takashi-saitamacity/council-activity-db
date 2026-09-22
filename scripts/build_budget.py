#!/usr/bin/env python3
"""正本予算提案PDF（2021〜2026年度）から budget_master.json / budget_master.csv を生成する。

    python scripts/build_budget.py --source-dir _budget_sources          # 生成
    python scripts/build_budget.py --source-dir _budget_sources --check  # 非破壊確認（CI用）

正本PDF自体はリポジトリに含めない。実行者がローカルに配置する。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "budget_master.json"
CSV_PATH = ROOT / "budget_master.csv"

FISCAL_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

PDF_FILENAMES = {y: f"{y}予算提案回答.pdf" for y in FISCAL_YEARS}

EXPECTED_SHA256 = {
    2021: "de043498c9611911780855d36c913343631ad82a478acbd86e160cbeafc73335",
    2022: "1324f201994c64a41d89b85a6411e2e6bdc90a2748dd63093203cd56a7c0616f",
    2023: "86d52012ceb3315b28bb0a307ff3215a6941cb33c619bcec4127032de30fadb8",
    2024: "c833c3fe29547419cee6d305fbc68358bbc1bb910b69d98a44628b38c0193248",
    2025: "822f5e4ac55999786d5ee5e9c0cd406ab5b51c84349fdbeeda1d0f8aa72fd6c6",
    2026: "0da1bb1a311e695d518060f196a0f2abfd35957f298a521a465780ed81012c2f",
}

# 2021〜2023年度は大項目1〜24、2024〜2026年度は大項目1〜15。
MAJOR_COUNT = {2021: 24, 2022: 24, 2023: 24, 2024: 15, 2025: 15, 2026: 15}

# 個別提案開始記号の様式。2021〜2023は〇/○（連番は出現順に付与）、
# 2024〜2026は丸数字（数字そのものをitem_noとする）。
ITEM_STYLE = {
    2021: "symbol", 2022: "symbol", 2023: "symbol",
    2024: "circled", 2025: "circled", 2026: "circled",
}

ITEM_SYMBOLS = ("〇", "○")
CIRCLED_DIGITS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

# 表紙直後に実在する既知の完全空白ページ（物理ページ番号は1始まり）。
# 抽出不良ではなく正本PDF自体に存在する空白ページとして確認済み。
KNOWN_BLANK_PAGES = {(2023, 2), (2024, 2), (2025, 2)}

# 回答マーカー欠落の既知allowlist例外（正本上、唯一の欠落）。
MISSING_ANSWER_MARKER_ALLOWLIST = {
    "2021-07-03": "放課後児童クラブ入室事務に関する保護者負担の軽減。",
}

# 正本から独立に抽出した完全性audit（抽出ロジックの入力には一切使わない）。
INDEPENDENT_AUDIT = {
    2021: [3, 1, 3, 3, 4, 2, 3, 2, 2, 2, 4, 6, 2, 3, 5, 2, 1, 3, 2, 9, 6, 6, 1, 1],
    2022: [3, 5, 5, 4, 7, 1, 4, 2, 2, 2, 5, 6, 4, 6, 4, 3, 2, 2, 4, 12, 5, 4, 1, 2],
    2023: [3, 7, 6, 6, 9, 6, 6, 3, 4, 5, 2, 5, 6, 6, 4, 3, 2, 4, 4, 5, 4, 6, 2, 4],
    2024: [4, 6, 5, 16, 10, 11, 7, 7, 6, 9, 10, 8, 7, 6, 3],
    2025: [5, 5, 6, 14, 10, 13, 11, 13, 6, 6, 7, 6, 8, 5, 7],
    2026: [5, 4, 6, 17, 5, 7, 13, 9, 6, 6, 4, 8, 5, 6, 4],
}
GRAND_TOTAL_EXPECTED = 625

MASTER_FIELDS = ["fiscal_year", "source_locator", "major_no", "major_title", "item_no", "proposal_text"]

MAJOR_RE = re.compile(r"^([０-９0-9]+)[．.](.*)$")
ANSWER_MARKER_RE = re.compile(r"[（(]回答[）)]")
PAGENO_PLAIN_RE = re.compile(r"^[0-9]+$")
PAGENO_DASH_RE = re.compile(r"^- [0-9]+ -$")
SOURCE_LOCATOR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FULLWIDTH_DIGITS = "０１２３４５６７８９"
_FW_TO_HW = str.maketrans(FULLWIDTH_DIGITS, "0123456789")


class BuildError(Exception):
    """正本の想定と異なる状態を検出した場合のFAIL。"""


def fw_to_int(s: str) -> int:
    return int(s.translate(_FW_TO_HW))


def circled_to_int(ch: str) -> int:
    return CIRCLED_DIGITS.index(ch) + 1


# ---------------------------------------------------------------------------
# 1〜6: 正本PDFの存在確認・SHA-256確認・pdftotext環境確認
# ---------------------------------------------------------------------------

def check_source_files(source_dir: pathlib.Path) -> dict[int, pathlib.Path]:
    paths: dict[int, pathlib.Path] = {}
    missing = []
    for year in FISCAL_YEARS:
        p = source_dir / PDF_FILENAMES[year]
        if not p.is_file():
            missing.append(str(p))
        else:
            paths[year] = p
    if missing:
        raise BuildError("正本PDFが不足しています:\n  " + "\n  ".join(missing))
    return paths


def check_sha256(paths: dict[int, pathlib.Path]) -> dict[int, str]:
    actual: dict[int, str] = {}
    mismatches = []
    for year, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        actual[year] = digest
        if digest != EXPECTED_SHA256[year]:
            mismatches.append(f"{year}: expected={EXPECTED_SHA256[year]} actual={digest}")
    if mismatches:
        raise BuildError("正本PDFのSHA-256が一致しません:\n  " + "\n  ".join(mismatches))
    return actual


def get_pdftotext_version() -> str:
    try:
        proc = subprocess.run(["pdftotext", "-v"], capture_output=True)
    except FileNotFoundError as e:
        raise BuildError("pdftotextが見つかりません（poppler-utilsが未導入です）") from e
    text = (proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace"))
    m = re.search(r"pdftotext version (\S+)", text)
    if not m:
        raise BuildError(f"pdftotextのバージョンを取得できません: {text!r}")
    return m.group(1)


# ---------------------------------------------------------------------------
# 5, 12: pdftotext -layout 実行、\f保持、物理ページ分割・ページ番号検証/除去
# ---------------------------------------------------------------------------

def run_pdftotext(pdf_path: pathlib.Path) -> str:
    proc = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True)
    stderr_text = proc.stderr.decode("utf-8", errors="replace")
    if re.search(r"missing language pack", stderr_text, re.IGNORECASE):
        raise BuildError(
            f"pdftotextは存在するが、日本語language dataが不足している: {pdf_path}\nstderr: {stderr_text}"
        )
    if proc.returncode != 0:
        raise BuildError(f"pdftotextが異常終了しました: {pdf_path} (rc={proc.returncode})\nstderr: {stderr_text}")
    return proc.stdout.decode("utf-8")


def get_pdf_page_count(pdf_path: pathlib.Path) -> int:
    proc = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True)
    if proc.returncode != 0:
        raise BuildError(f"pdfinfoが失敗しました: {pdf_path}")
    text = proc.stdout.decode("utf-8", errors="replace")
    m = re.search(r"^Pages:\s*(\d+)", text, re.MULTILINE)
    if not m:
        raise BuildError(f"pdfinfoからページ数を取得できません: {pdf_path}")
    return int(m.group(1))


def split_physical_pages(full_text: str, fiscal_year: int, pdf_path: pathlib.Path) -> list[str]:
    """\\f を保持したまま物理ページへ分割する。末尾の空要素のみ無視し、
    それ以外の位置に現れる空要素はFAILとする（既知allowlistページを除く）。"""
    parts = full_text.split("\f")

    # 末尾に生じる空（空白のみ含む）要素は、pdftotextの末尾\fによる無害な
    # 分割アーティファクトなので無視する。
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]

    expected_pages = get_pdf_page_count(pdf_path)
    if len(parts) != expected_pages:
        raise BuildError(
            f"{fiscal_year}: \\f分割によるページ数({len(parts)})がpdfinfoのページ数({expected_pages})と一致しません"
        )

    for idx, part in enumerate(parts):
        physical_page = idx + 1
        if part.strip() == "":
            if physical_page == 1:
                raise BuildError(f"{fiscal_year}: 物理ページ1（表紙）が空白です。想定と異なります。")
            if (fiscal_year, physical_page) not in KNOWN_BLANK_PAGES:
                raise BuildError(
                    f"{fiscal_year}: 物理ページ{physical_page}が空白ですが、"
                    "既知allowlistに含まれていません（正本のページ構造が想定と異なる）"
                )
    return parts


def strip_page_number(fiscal_year: int, physical_page: int, page_text: str) -> str | None:
    """1ページ分のテキストからページ番号行を検証・除去する。
    表紙(物理1ページ目)と既知の空白allowlistページは検証をスキップする。
    allowlistページはNoneを返し、以降の解析対象から除外する。
    """
    if physical_page == 1:
        return page_text

    if (fiscal_year, physical_page) in KNOWN_BLANK_PAGES:
        if page_text.strip() != "":
            raise BuildError(
                f"{fiscal_year}: 物理ページ{physical_page}はallowlist対象の空白ページのはずですが、"
                "内容が存在します。"
            )
        return None

    lines = page_text.split("\n")
    last_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() != "":
            last_idx = i
            break

    if last_idx is None:
        raise BuildError(
            f"{fiscal_year}: 物理ページ{physical_page}が予期せず空白です"
            "（正本のページ構造が想定と異なる）"
        )

    candidate = lines[last_idx].strip()
    if PAGENO_PLAIN_RE.fullmatch(candidate) or PAGENO_DASH_RE.fullmatch(candidate):
        new_lines = lines[:last_idx] + lines[last_idx + 1:]
        return "\n".join(new_lines)

    raise BuildError(
        f"{fiscal_year}: 物理ページ{physical_page}の末尾行 {candidate!r} が"
        "想定のページ番号形式（数字のみ、または '- 数字 -'）に一致しません"
        "（正本のページ構造が想定と異なる）"
    )


def extract_body_lines(fiscal_year: int, pdf_path: pathlib.Path) -> list[str]:
    full_text = run_pdftotext(pdf_path)
    pages = split_physical_pages(full_text, fiscal_year, pdf_path)

    kept_pages = []
    for idx, page_text in enumerate(pages):
        physical_page = idx + 1
        processed = strip_page_number(fiscal_year, physical_page, page_text)
        if processed is not None:
            kept_pages.append(processed)

    body_lines: list[str] = []
    for page in kept_pages:
        body_lines.extend(page.split("\n"))
    return body_lines


# ---------------------------------------------------------------------------
# 11〜15: 大項目・個別提案・回答境界・proposal_text抽出
# ---------------------------------------------------------------------------

def parse_year(fiscal_year: int, body_lines: list[str]) -> list[dict]:
    style = ITEM_STYLE[fiscal_year]
    expected_major_count = MAJOR_COUNT[fiscal_year]

    # 1st pass: 大項目・個別提案マーカーの行位置を確定する。
    events: list[tuple] = []  # ('major', major_no, title, line_idx) / ('item', value_or_None, line_idx)
    expected_next_major = 1
    for idx, line in enumerate(body_lines):
        ls = line.lstrip()
        if not ls:
            continue

        m = MAJOR_RE.match(ls)
        if m and fw_to_int(m.group(1)) == expected_next_major:
            title = m.group(2).strip()
            events.append(("major", expected_next_major, title, idx))
            expected_next_major += 1
            continue

        if style == "symbol":
            if ls[0] in ITEM_SYMBOLS:
                events.append(("item", None, idx))
                continue
        else:
            if ls[0] in CIRCLED_DIGITS:
                events.append(("item", circled_to_int(ls[0]), idx))
                continue

    major_events = [e for e in events if e[0] == "major"]
    if len(major_events) != expected_major_count:
        found = [e[1] for e in major_events]
        raise BuildError(
            f"{fiscal_year}: 大項目番号が想定({1}〜{expected_major_count})と一致しません "
            f"(検出した大項目: {found})"
        )

    for e in major_events:
        if e[2].strip() == "":
            raise BuildError(f"{fiscal_year}: 大項目{e[1]}のmajor_titleが空です")

    records: list[dict] = []
    for m_i, major_event in enumerate(major_events):
        major_no = major_event[1]
        major_title = major_event[2]
        major_start = major_event[3]
        major_end = major_events[m_i + 1][3] if m_i + 1 < len(major_events) else len(body_lines)

        item_events = [e for e in events if e[0] == "item" and major_start < e[2] < major_end]
        if not item_events:
            raise BuildError(f"{fiscal_year}: 大項目{major_no}に個別提案が1件も見つかりません")

        if style == "circled":
            values = [e[1] for e in item_events]
            expected_values = list(range(1, len(values) + 1))
            if sorted(values) != expected_values or values != expected_values:
                raise BuildError(
                    f"{fiscal_year}: 大項目{major_no}の丸数字番号が連番になっていません "
                    f"(検出順: {values}, 期待: {expected_values})"
                )
            item_numbers = values
        else:
            item_numbers = list(range(1, len(item_events) + 1))

        for i_i, item_event in enumerate(item_events):
            item_no = item_numbers[i_i]
            item_start = item_event[2]
            item_end = item_events[i_i + 1][2] if i_i + 1 < len(item_events) else major_end

            first_line = body_lines[item_start].lstrip()
            first_line_remainder = first_line[1:].lstrip()  # マーカー1文字＋直後の空白を除去

            fragments = [first_line_remainder]
            for j in range(item_start + 1, item_end):
                fragments.append(body_lines[j].strip())
            item_full_text = "".join(fragments)

            source_locator = f"{fiscal_year}-{major_no:02d}-{item_no:02d}"

            match = ANSWER_MARKER_RE.search(item_full_text)
            if match is not None:
                proposal_text = item_full_text[: match.start()]
            else:
                expected = MISSING_ANSWER_MARKER_ALLOWLIST.get(source_locator)
                if expected is None:
                    raise BuildError(
                        f"{fiscal_year}: {source_locator} は通常項目ですが回答マーカーが見つかりません"
                    )
                if not item_full_text.startswith(expected):
                    raise BuildError(
                        f"{source_locator}: allowlist例外のproposal_textが期待値と不一致です\n"
                        f"  期待: {expected!r}\n"
                        f"  実際(先頭): {item_full_text[:len(expected) + 20]!r}"
                    )
                proposal_text = expected

            if proposal_text == "":
                raise BuildError(f"{source_locator}: proposal_textが空です")

            if not SOURCE_LOCATOR_RE.fullmatch(source_locator):
                raise BuildError(f"source_locatorの形式が不正です: {source_locator}")

            records.append({
                "fiscal_year": fiscal_year,
                "source_locator": source_locator,
                "major_no": major_no,
                "major_title": major_title,
                "item_no": item_no,
                "proposal_text": proposal_text,
            })

    return records


# ---------------------------------------------------------------------------
# 16〜19: マスター生成・独立audit
# ---------------------------------------------------------------------------

def build_master(source_dir: pathlib.Path) -> list[dict]:
    paths = check_source_files(source_dir)
    check_sha256(paths)
    version = get_pdftotext_version()
    print(f"pdftotext version: {version}")

    all_records: list[dict] = []
    for year in FISCAL_YEARS:
        body_lines = extract_body_lines(year, paths[year])
        records = parse_year(year, body_lines)
        all_records.extend(records)

    audit_master(all_records)
    return all_records


def audit_master(records: list[dict]) -> None:
    locators = [r["source_locator"] for r in records]
    if len(locators) != len(set(locators)):
        dupes = sorted({loc for loc in locators if locators.count(loc) > 1})
        raise BuildError(f"source_locatorが重複しています: {dupes}")

    for r in records:
        if not r["proposal_text"]:
            raise BuildError(f"{r['source_locator']}: proposal_textが空です")
        if not r["major_title"]:
            raise BuildError(f"{r['source_locator']}: major_titleが空です")
        if not SOURCE_LOCATOR_RE.fullmatch(r["source_locator"]):
            raise BuildError(f"source_locatorの形式が不正です: {r['source_locator']}")

    if len(records) != GRAND_TOTAL_EXPECTED:
        raise BuildError(f"grand totalが{GRAND_TOTAL_EXPECTED}件ではありません（実際: {len(records)}件）")

    # 独立audit（年度別・大項目別）との突合。抽出ロジックの入力には使っていない。
    for year in FISCAL_YEARS:
        year_records = [r for r in records if r["fiscal_year"] == year]
        expected_total = sum(INDEPENDENT_AUDIT[year])
        if len(year_records) != expected_total:
            raise BuildError(
                f"{year}: 年度別audit件数が一致しません（実際: {len(year_records)}, 期待: {expected_total}）"
            )
        by_major: dict[int, int] = {}
        for r in year_records:
            by_major[r["major_no"]] = by_major.get(r["major_no"], 0) + 1
        actual_counts = [by_major.get(i + 1, 0) for i in range(len(INDEPENDENT_AUDIT[year]))]
        if actual_counts != INDEPENDENT_AUDIT[year]:
            raise BuildError(
                f"{year}: 大項目別audit件数が一致しません\n  実際: {actual_counts}\n  期待: {INDEPENDENT_AUDIT[year]}"
            )

    # 2021-07-03 allowlist例外の検証。
    target = next((r for r in records if r["source_locator"] == "2021-07-03"), None)
    if target is None:
        raise BuildError("2021-07-03が生成結果に存在しません")
    expected_text = MISSING_ANSWER_MARKER_ALLOWLIST["2021-07-03"]
    if target["proposal_text"] != expected_text:
        raise BuildError(
            f"2021-07-03のproposal_textが期待値と不一致です: {target['proposal_text']!r}"
        )

    # 2023年度 duplicate proposal_text（同一提案文が2大項目に掲載）の保存確認。
    loc_map = {r["source_locator"]: r for r in records}
    for loc in ("2023-09-02", "2023-19-04"):
        if loc not in loc_map:
            raise BuildError(f"{loc} が生成結果に存在しません")
    if loc_map["2023-09-02"]["proposal_text"] != loc_map["2023-19-04"]["proposal_text"]:
        raise BuildError("2023-09-02 と 2023-19-04 のproposal_textが一致しません")


# ---------------------------------------------------------------------------
# 17〜18: JSON/CSV 生成
# ---------------------------------------------------------------------------

def render_json(records: list[dict]) -> str:
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"


def render_csv(records: list[dict]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(MASTER_FIELDS)
    for r in records:
        writer.writerow([r[f] for f in MASTER_FIELDS])
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, help="正本PDFが置かれているディレクトリ")
    parser.add_argument("--check", action="store_true", help="書き換えず、正本との一致だけを確認する")
    args = parser.parse_args()

    source_dir = pathlib.Path(args.source_dir)

    try:
        records = build_master(source_dir)
    except BuildError as e:
        print(f"NG: {e}")
        return 1

    json_text = render_json(records)
    csv_text = render_csv(records)

    if args.check:
        problems = []
        current_json = JSON_PATH.read_text(encoding="utf-8") if JSON_PATH.exists() else None
        current_csv = CSV_PATH.read_text(encoding="utf-8") if CSV_PATH.exists() else None
        if current_json != json_text:
            problems.append(f"{JSON_PATH.name} が正本から生成される内容と一致しません")
        if current_csv != csv_text:
            problems.append(f"{CSV_PATH.name} が正本から生成される内容と一致しません")
        if problems:
            print("NG:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"OK: budget_master.json / budget_master.csv は正本と一致（total={len(records)}）")
        return 0

    JSON_PATH.write_text(json_text, encoding="utf-8")
    CSV_PATH.write_text(csv_text, encoding="utf-8")
    print(f"生成しました: {JSON_PATH.name}, {CSV_PATH.name}（total={len(records)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
