"""予算提案の年度別 source_url 定数表。

正本: council-activity-private/v1.2.0/specs/budget_step10_spec.md §4。
値はそこからそのまま転記したものであり、このリポジトリ側で生成・推測しない。

reflect_budget_step10.py と finalize_budget_source_urls.py の両方がこの
定数を import して使う。年度別URLをスクリプトごとに個別に持たない。
"""
from __future__ import annotations

SOURCE_URL: dict[int, str] = {
    2021: "https://democracy-saitamacity.jp/wp-content/uploads/2021/07/%E6%B0%91%E4%B8%BB%E6%94%B9%E9%9D%A9%E3%81%95%E3%81%84%E3%81%9F%E3%81%BE%E5%B8%82%E8%AD%B0%E5%9B%A3%E3%81%B8%E3%81%AE%E5%9B%9E%E7%AD%94.pdf",
    2022: "https://democracy-saitamacity.jp/wp-content/uploads/2022/01/%E6%B0%91%E4%B8%BB%E6%94%B9%E9%9D%A9%E3%81%95%E3%81%84%E3%81%9F%E3%81%BE%E5%B8%82%E8%AD%B0%E5%9B%A3%E3%80%8C%EF%BC%92%EF%BC%90%EF%BC%92%EF%BC%92%E5%B9%B4%E5%BA%A6%E3%80%80%E4%BA%88%E7%AE%97%E7%B7%A8%E6%88%90%E4%B8%A6%E3%81%B3%E3%81%AB%E6%96%BD%E7%AD%96%E3%81%AB%E5%AF%BE%E3%81%99%E3%82%8B%E6%8F%90%E6%A1%88%E3%80%8D%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6.pdf",
    2023: "https://democracy-saitamacity.jp/wp-content/uploads/2023/01/63da8853abc9bafc8641575be5f163ef.pdf",
    2024: "https://democracy-saitamacity.jp/wp-content/uploads/2024/02/dc6ffc0f7ab75190896c401b61d2946a.pdf",
    2025: "https://democracy-saitamacity.jp/wp-content/uploads/2025/02/1230c153ea53d2af4b8f75b7257e37d0.pdf",
    2026: "https://democracy-saitamacity.jp/wp-content/uploads/2026/01/1c8bf596ee31e907d9824ed2d496148a.pdf",
}
