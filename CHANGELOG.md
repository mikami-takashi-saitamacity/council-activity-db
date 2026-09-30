# 変更履歴

データの版ごとの変更を記録します。件数の増減に加え、対応状況(result_level)の判定を変更した場合は、その件数もここに記載します(判定は議員本人によるため、変更の履歴を公開しておくことが検証可能性の担保になります)。

## [1.3.3] - 2026-09-30

- 収録件数の増減なし(1,343件のまま)。result_levelの変更は0件
- `mikami-000869`の`source_url`を訂正。`council_id=775&schedule_id=2`の`minute_id` 314 → 275(v1.3.2の訂正前のURLに戻した。三神が2026-09-30にブラウザで確認済み)
- v1.3.2での`mikami-000869`の訂正(275 → 314)は誤りだった。314は同じ日の別カード(`mikami-000868`の論点)のブロックで、275が正しかった。誤りの原因は、カードの型を取り違えたこと。`mikami-000869`は討論の型のカードだったが、質疑のブロックを探して314を選んだ
- v1.3.2の他の3件(`mikami-000927`・`mikami-001306`・`mikami-001058`)の訂正は変更なし

## [1.3.2] - 2026-09-30

- 収録件数の増減なし(1,343件のまま)。result_levelの変更は0件
- 議事録4件の`source_url`を訂正(いずれも三神がブラウザで確認済み)。`minute_id`のみ変更し、`council_id`・`schedule_id`は変更なし
  - `mikami-000869`:`council_id=775&schedule_id=2`、`minute_id` 275 → 314(旧URLは討論のブロックを指していた)
  - `mikami-000927`:`council_id=690&schedule_id=4`、`minute_id` 318 → 345(旧URLは討論のブロックを指していた)
  - `mikami-001306`:`council_id=210&schedule_id=1`、`minute_id` 163 → 256(旧URLは別の論点のブロックを指していた)
  - `mikami-001058`:`council_id=507&schedule_id=7`、`minute_id` 99 → 128(旧URLは審査経過の報告のブロックを指していた)

## [1.3.1] - 2026-09-29

- 収録件数の増減なし(1,343件のまま)。result_levelの変更は0件
- `mikami-000651`〜`000659`(9件)の`source_url`を訂正。`council_id=1047&schedule_id=8&minute_id=206`(誤って別の日を指していた)から、`council_id=1047&schedule_id=6`の`minute_id=377`(000651・000652）／`383`（000653〜000655）／`391`（000656〜000658）／`399`（000659）へ修正
- v1.3.0のtag(`350de94d`)以後にmainへ反映されていた README・CHANGELOG の文言訂正([#21](https://github.com/mikami-takashi-saitamacity/council-activity-db/pull/21)、[#22](https://github.com/mikami-takashi-saitamacity/council-activity-db/pull/22)、[#23](https://github.com/mikami-takashi-saitamacity/council-activity-db/pull/23))を、本版に含める
- CITATION.cffの`version`がv1.3.0公開時に`1.2.0`のまま更新されていなかったため、本版で`1.3.1`に更新した

## [1.3.0] - 2026-09-28

- 1,343件（議事録718件／会派予算提案625件）を正式公開
- 議事録へ正式ID `mikami-000626`〜`mikami-001344` を付与。重複削除した `mikami-000873` はretiredとして記録し、現存1,343件を恒久ID化
- 本人発言2,009 spanは、AI支援による照合で直接対応1,507・除外502・未解決0に整理。三神が数件〜数十件ずつ公開候補を確認し、一部修正しながら順次承認した。本人が各カードを1件ずつ原文照合したことを意味しない
- 質問・質疑と答弁を収録対象として再抽出し、討論・採決のみの発言を対象外に整理
- 旧URL666件は、665件を現行カードへ正式IDで解決し、削除1件を理由付き告知として維持。重複だった旧URL2件は同じ現行カードへ収束
- DB PR #19の事実訂正を公開版へ反映。音声コードURLを修正し、2018年12月10日の重複1件を削除、給与差押えカードを質疑・質問の範囲だけで再構成
- v1.2.0のRelease・tag（967件）は未変更。公開DB・サイトのv1.3.0対象commitはそれぞれ `350de94da8c226ee7ca48bf657ffb712d53667e2`、`0018baafd8df3e9775c6557c5ce11c835b65f30c`

## [1.2.0] - 2026-09-25

- 収録:967件(議事録342件/会派予算提案625件)。v1.1.0(全666件、議事録342件/会派予算提案324件)から会派予算提案が301件増加
- スキーマ:v1.1.0 → v1.2.0。propertyを追加(`id`・`source_status`・`source_locator`・`fiscal_year`・`follow_up_evidence`)。requiredに`source_status`・`tags`を追加。`tags`の15分類語彙・`result_level`の6区分enumはv1.1.0から変更なし。`follow_up_evidence`はスキーマに追加したが、現production dataでの使用レコードは0件
- 会派予算提案625件:2021〜2026年度の市の正本回答書を基準に全項目を再整理し、正式ID(`mikami-000001`〜`mikami-000625`)を付与。`date`を実際の提出日へ整理し、`meeting_type`を整理。`source_locator`・`fiscal_year`を整備。625件全件で`source_url`を整備
- 議事録`source_url`:人手確認対象31件を確認し、30件を修復、1件は既存値が正しいことを確認。現在の`source_url`整備状況は967件中688件(議事録342件中63件、予算提案625件中625件)
- `source_status`を導入(`official`/`provisional`)。`provisional`は開催日から暦5か月超で警告する仕組みを追加(warningのみ、CI failureにはしない)。現production dataは`official` 967件・`provisional` 0件
- 旧URL互換666件を維持
- result_level変更:120件(議事録342件は0件変更、既存の会派予算提案324件で120件変更)
- 会派予算提案625件のresult_levelは各年度の市回答時点の評価を保存しており、後年の実現状況を過去年度の評価には混ぜていない。一方、旧データベース由来の議事録342件には、後年の実現を受けた再判定が混入している可能性があり、v1.3.0で再抽出・再監査を予定している(967件すべてが当時評価というわけではない)

## [1.1.0] - 2026-08-31

- 収録:666件(議事録342件/会派予算提案324件)。2007年6月〜2026年2月の発言分
- スキーマ:v1.1.0(15分野タグ、result_level 6区分)
- 2026-09-02 追記:引用情報(CITATION.cff)・検証スクリプト・自動検証の仕組みを追加([#2](https://github.com/mikami-takashi-saitamacity/council-activity-db/pull/2))。構造上の既知の課題を README に明記([#1](https://github.com/mikami-takashi-saitamacity/council-activity-db/issues/1))。データ本体(666件)は 2026-08-31 から変更なし
