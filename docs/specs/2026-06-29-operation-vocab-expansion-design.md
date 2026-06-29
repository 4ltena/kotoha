# デスクトップ操作 語彙拡張 — 設計

2026-06-29。デスクトップ操作グラウンディング(v1)に、ドラッグ・複数操作の連鎖・grounding の自己整合チェックを足す。設計の正は本書、土台は [操作グラウンディング設計](2026-06-29-desktop-operation-grounding-design.md)。

## 方針

v1 の安全多層(既定OFF / dry-run 既定 / allowlist 空=全拒否 / 破壊確認 / global kill / FAILSAFE / 1発話1操作)は崩さない。拡張はいずれも既存ゲートの上に積み、各ステップで grounding・allowlist・破壊判定を個別にかける。連鎖は `operation_max_actions_per_command` を 1 より大きく明示設定したときだけ有効で、既定 1 のままなら従来どおり 1 発話 1 操作。

## 追加する操作と仕組み

### drag(ドラッグ)

- `ActionRequest` に `to_target: str = ""` を足す。drag の移動先記述を保持する。
- kind `"drag"`。発話「AをBにドラッグして / AをBへ移動して / AをBに動かして」を `parse_intent` が `ActionRequest("drag", target="A", to_target="B")` にする。
- **抽出規則**: drag キーワード集合は `("ドラッグ", "移動", "動かし")`。パターン `<A>を … <B>に|へ … <drag語>` に対し、A は「を」より前の句、B は「に|へ」と drag 語の間の句として取り、それぞれ既存 `_extract_target`(末尾助詞除去・30字上限・指示詞のみは "")で整える。**drag 検出は click/double_click の分岐より前**に置く(「ドラッグ」発話が click へ落ちないため)。A か B のどちらかが空なら drag として扱わず素通し(None)。`移動`/`動かし` は汎用語なので、「を…に|へ」の2引数パターンが揃ったときだけ drag とみなす。
- drag は from(A)と to(B)を**それぞれ grounding** して2点の座標を得る。`actuator` の `drag(x1,y1,x2,y2)` で from から to へドラッグする(`pyautogui.moveTo` → `dragTo`)。
- `is_destructive` は drag の `target`・`to_target` も対象文に含める。ただし破壊判定は `operation_destructive_keywords` への一致に依存するため、ゴミ箱へのドラッグを破壊的と拾うには既定キーワードに `ゴミ箱`・`ごみ箱` を加える(後述の設定変更)。`to_target` の配線だけでは「ゴミ箱」は既定語に一致しない点に注意。

### 複数操作の連鎖

- 新規 `parse_chain(text, config) -> list[ActionRequest]`。接続語(「そして」「それから」「、」)で発話を節に割り、各節を既存の単一意図ロジック(`parse_intent`)で解析して非 None を集める。接続語が無ければ全体を 1 意図として解析する。空なら `[]`(操作意図なし)。`してから`/`てから` のような て形連結は動詞活用と重なって節を壊すため接続語に含めず、形態素分割が要るそれらは後続へ送る。
- **引用テキストを保護する分割**。`「…」`/`『…』` で囲まれた範囲は分割対象から除外する。`「a、b」と入力してから、Xして` のように引用内の `、` を接続語と誤認して型入力文字列を壊さないため、まず引用範囲を `_QUOTED` の境界で退避(マスク)し、残りのテキストから接続語を探して分割し、復元してから各節を `parse_intent` する。
- `Operator` は `parse_intent` の代わりに `parse_chain` を使い、得たリストを順に実行する。
- **各ステップで個別にゲートを通す**。ステップごとに再キャプチャ・再 grounding・`app_allowed` 再評価をする(画面はステップ間で変わるため、座標は毎回取り直す)。
- `operation_max_actions_per_command` が連鎖長の上限。`actuator.begin_command()` を**連鎖開始時に 1 回だけ**呼んでカウントを 0 に戻し(ステップごとには呼ばない)、各ステップの `execute` がカウントを増やす。連鎖長が上限を超えると以降の `execute` は False を返し、そのステップで連鎖を打ち切る。**カウントを消費するのは `actuator.execute` が呼ばれたステップだけ**で、execute 到達前(capture / grounding / allowlist)で失敗したステップは予算を消費しない(現 `actuator` は `execute` 内でのみ `_count` を増やす)。
- `kill`/FAILSAFE は連鎖全体に効く。途中で `aborted()` になったら残りを実行せず中止を返す。
- いずれかのステップで capture / grounding / allowlist が失敗したら、そのステップで連鎖を打ち切り `[操作失敗] {理由}` を返す(部分実行は起こりうるが、各ステップが独立にゲートを通っているため未許可操作は実行されない)。
- **結果文の集約と部分実行**。デスクトップの副作用は取り消せないため、`_run_chain` は実行した各ステップを列挙し、打ち切り時は中止位置と理由を添えた集約文を返す(例 `ステップ1: 〈検索〉を操作 / ステップ2: [操作失敗] 対象が見つからない (2/3で中止)`)。dry-run でも各ステップを列挙して、複数ステップの連鎖が試行されたことが分かるようにする。完了済みステップはロールバックしない。

### 破壊確認(連鎖全体を 1 回)

- 連鎖中に **1 つでも破壊的ステップ**があり `confirm_destructive` が真なら、**連鎖全体を 1 回の音声確認でゲート**する。pending に連鎖(`list[ActionRequest]`)と原発話を保存し、確認文を返す。肯定で連鎖を実行(各ステップは個別にゲート)、否定で取りやめ。**肯定でも否定でもない応答**は v1 と同じく pending を破棄し、その発話を新しい意図として `parse_chain` で解析し直す。pending の TTL 失効も v1 と同じ。
- 無害のみの連鎖は即実行する。
- ステップ単位の 2 ターン握手を連鎖の途中で挟む(中断・再開状態を持つ)のは本フェーズのスコープ外とし、後続へ送る。各ステップの grounding・allowlist ゲートは個別に効くため、未許可アプリや見つからない対象での実行は連鎖でも起きない。

### grounding 自己整合チェック(信頼度しきい値棄却)

- Holo2 は信頼度スコアを返さないため、信頼度の代理として**同一対象を 2 回 grounding し、2 つの座標が許容差を超えてばらつけば棄却**する(低信頼=操作せず「対象が曖昧」を返す)。
- 設定 `operation_grounding_self_check: bool = False`(既定 OFF。レイテンシ倍化を避ける)、`operation_grounding_tolerance_px: int = 30`。棄却条件は **Chebyshev 距離** `max(|x1-x2|, |y1-y2|) > operation_grounding_tolerance_px`(例 (100,200) と (150,210) は |Δx|=50 > 30 で棄却)。
- 自己整合チェックは click 系の対象と drag の from/to のそれぞれに適用する。OFF のときは 1 回 grounding で従来どおり。破壊操作を実作動させる環境では ON を推奨する。

## コンポーネント

- `kotoha/operate/actions.py`(改)。`ActionRequest` に `to_target=""`。drag の検出と from/to 抽出を `parse_intent` に追加。`parse_chain(text, config) -> list[ActionRequest]` を新設。
- `kotoha/operate/policy.py`(改)。`is_destructive` の対象文に `to_target` を加える。
- `kotoha/operate/actuator.py`(改)。`execute(action, *, coords, coords_to=None)` へ拡張(drag は coords=from、coords_to=to)。`_do` と `_describe_action` に drag を追加。`_PyAutoGuiBackend.drag(x1,y1,x2,y2)`。
- `kotoha/operate/operator.py`(改)。`parse_chain` を使い、連鎖実行(`_run_chain`)・連鎖全体の破壊確認・自己整合 grounding(`_ground_checked`)を実装。pending を連鎖(list)へ拡張。
- `kotoha/config.py`(改)と `.env.example`(改)。`operation_grounding_self_check: bool = False` / `operation_grounding_tolerance_px: int = 30` を足す。`operation_destructive_keywords` の既定に `ゴミ箱`・`ごみ箱` を加える(drag-to-trash を破壊的と分類するため)。`operation_max_actions_per_command` は既存(既定 1)。
- `kotoha/operate/proof.py`(改、任意)。drag/連鎖の単体確認手段は本フェーズでは proof CLI を大きく変えず、既存の単一指示 proof を流用する(連鎖の proof は後続)。

## データフロー

発話 → `parse_chain` で `[ActionRequest, ...]`。空なら何もしない。連鎖に破壊ステップがあり確認設定が真なら pending へ保存して確認文を返す。実行(即時 or 肯定後)は `_run_chain`: `begin_command` → 各 action について「再キャプチャ → (click/drag なら自己整合 grounding) → `app_allowed` 再評価 → `execute`」を順に行い、失敗・kill で打ち切る。結果文(各ステップの要約)を会話へ注入する。

## 安全機構(不変 + 追加)

- 既定 OFF / dry-run 既定 / allowlist 空=全拒否 / 破壊確認 / global kill / FAILSAFE は v1 から不変。
- 連鎖は `operation_max_actions_per_command > 1` を明示したときだけ有効(既定 1)。各ステップが個別に grounding・allowlist・(破壊確認は連鎖単位)を通る。
- dry-run は drag・連鎖を含む全 kind の実副作用を抑止する(`actuator.execute` の dry-run ガードは kind 分岐の手前)。
- 自己整合チェックは ON のとき低信頼 grounding を棄却し、曖昧な対象でのクリック/ドラッグを防ぐ。

## エラー処理

best-effort を維持する。drag の 2 点 grounding のどちらか、連鎖の途中ステップ、自己整合チェックの不一致、いずれも `[操作失敗] {理由}` か棄却を返すだけで会話・声ループを止めない。`actuator` は drag を含め例外・FAILSAFE・kill を握って False を返す。

## テスト

ユニットは fake のみ(この環境は実作動・モデル DL をしない)。検証する観点:
- `parse_intent` の drag 検出と from/to 抽出(「AをBにドラッグ」→ target=A/to_target=B、片方空なら非 drag、click より前で検出)。
- `parse_chain` の接続語分割と各節解析、接続語なしの単一化、空、**引用テキスト保護**(`「a、b」と入力してから、Xして` は型入力を壊さず 2 節になる)。
- `is_destructive` の `to_target` 反映と、**drag-to-trash**(target="ファイル", to_target="ゴミ箱")が True になること(既定キーワードに ゴミ箱 追加後)。
- `actuator` の drag dispatch(coords + coords_to)・dry-run が drag を含む全 kind を抑止・既存単一 coords 呼び出しが壊れないこと。
- `Operator` の連鎖実行(各ステップ個別の再 grounding・allowlist 再評価、max_actions 打ち切り、kill 中断、連鎖全体の破壊確認握手と中立応答の再解析、部分実行時の集約結果文)。
- 自己整合 grounding(2 回が許容差内なら採用、Chebyshev 距離が許容超なら棄却)。

実 grounding・実作動・drag の実機確認は rig の proof と後続に委ねる。

## 受け入れ基準

「AをBにドラッグして」で A から B へドラッグできる。`operation_max_actions_per_command` を上げると「Xして、それからYして」のような連鎖を 1 発話で実行でき、各ステップは個別に grounding と allowlist を通り、連鎖に破壊操作が含まれれば連鎖全体を 1 回確認してから実行する。自己整合チェックを有効にすると、grounding が安定しない曖昧な対象では操作せず「対象が曖昧」を返す。kill とFAILSAFE は連鎖の途中でも止める。dry-run・既定 OFF・allowlist 全拒否は維持される。既定設定(max 1・self_check OFF)では v1 と挙動が変わらない。

## 未決・後続

- 連鎖途中でのステップ単位 2 ターン確認(中断・再開状態機械)は本フェーズのスコープ外。
- drag・連鎖の proof CLI 拡張は後続。
- 自己整合チェックの許容差・回数(2 回固定)は実機の grounding 揺れを見て調整する。
