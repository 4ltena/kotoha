# デスクトップ操作グラウンディング — 設計

2026-06-29。kotoha につくよみが「画面を操作する」能力を足す。画面知覚で固めた土台の上に、音声コマンドからキャプチャ → グラウンディング（指定 UI のクリック点を座標化）→ 実行のループを載せる。本 spec は単一フェーズで、グラウンディングと実作動と安全機構をまとめて扱う。設計の正は本書、知覚側の正は [画面知覚 Phase 1 設計](2026-06-28-screen-perception-design.md) と [Phase 2 設計](2026-06-29-screen-perception-phase2-design.md)。

知覚が「画面を見て要約を会話へ織り込む」までだったのに対し、操作は「見た画面の上で実際にマウス・キーボードを動かす」。副作用が初めて外界（ユーザーのデスクトップ）に及ぶため、安全機構を機能本体と同格に置く。

## 方針

知覚と同じく、グラウンディングのモデルは Apache-2.0 のものだけを使い、キャプチャと実行のループは kotoha 側に自前で持つ。閉じたランタイムには依存しない。

起動は会話の前段で行う。天気ツール（`kotoha/tools/`）が発話を LLM へ渡す前にキーワードで起動し結果を文脈へ注入するのと同型に、操作も発話を前段で解釈して「操作意図」を取り出し、グラウンディングと実行を済ませてから結果を文脈へ注入する。フロント LLM は従来どおり純テキストストリーミングのままで、tool-calling は導入しない。

実行は多層防御で囲む。既定は無効、有効化しても既定は dry-run（可視化のみ）、許可アプリのリストが空なら何も操作しない。破壊的な操作は音声で確認してから実行し、グローバル kill キーと FAILSAFE でいつでも止められる。1 発話につき 1 操作に限る。

スクリーンショットは知覚と同じくメモリ上だけで扱い、グラウンディングへ渡したら破棄する。残すのは座標と短い結果文だけで、外部 API へは何も送らない。

## 採用部品とライセンス

ライセンスは Hugging Face のモデルカードで実体を確認済み。商用可の permissive のみ。

| 用途 | 採用 | ライセンス | 備考 |
| --- | --- | --- | --- |
| グラウンディング VLM | Holo2-8B | Apache-2.0 | `Qwen/Qwen3-VL-8B-Thinking` からのファインチューン。GUI ローカライズ特化、座標出力に強い。思考トレースを吐きうる |
| 作動（マウス） | PyAutoGUI | BSD-3-Clause | 絶対座標クリック・スクロール。FAILSAFE 内蔵 |
| 作動（キーボード・kill） | keyboard | MIT | テキスト入力、ホットキー、グローバルフックによる中断キー |
| キャプチャ | mss（既存） | MIT | 知覚と共用。プライマリモニタの矩形も取れる |

サイズ別にライセンスが割れる罠は知覚と同じ。Holo2 で採用するのは **4B / 8B のみ**（ともに Apache-2.0）。30B-A3B・235B-A22B はサイズ表記が別で、研究・非商用条項の有無を都度確認する。本 spec は 8B を既定とする。

Holo2-8B の座標出力は **x, y を 0〜1000 で正規化した整数**で、入力画像のウィンドウサイズに依存しない。OpenAI 互換 API（`/v1/chat/completions` に画像を `image_url` で渡す）で呼べる。Holo2-8B 専用 GGUF は未確認のため、Qwen3-VL-8B ベースとして変換・量子化したものを別途用意する外部前提とする（GPT-SoVITS の参照音声と同じ扱い）。正規化座標の実出力形式は proof CLI で実機確認する。

## コンポーネント

新規パッケージ `kotoha/operate/` を `kotoha/screen/` と対称に置く。純ロジックと副作用を分け、副作用は `actuator.py` 一つに閉じ込める。重い依存（`pyautogui` / `keyboard`）はメソッド・`__init__` 内で遅延 import する。`sounddevice` を `speaker.py`/`mic.py` で、`mss` を `capture.py` で遅延 import している既存の流儀に合わせる。

- `kotoha/operate/grounding.py`（新・純パース + 1 async）。Holo2 へ画像と指示を送り、正規化座標を実 OS 座標へ写像する。
  - `Region(left, top, width, height)`。キャプチャしたモニタ矩形（OS 座標）。
  - `GroundResult(x, y, raw)`。x, y は写像済みの実 OS 座標。raw は応答原文。
  - `parse_ground_response(text) -> tuple[int, int] | None`（純）。正規化座標 (nx, ny) を返す。手順を固定する。(1) `<think>…</think>` を非貪欲（`re.DOTALL`）で全除去。(2) 正規表現を順に試す: `click\(\s*(\d+)\s*,\s*(\d+)\s*\)` → `\(\s*(\d+)\s*,\s*(\d+)\s*\)` → `"x"\s*:\s*(\d+).*?"y"\s*:\s*(\d+)`。(3) 最初に一致した 1 組だけ採用。(4) いずれかが 0〜1000 の範囲外・負値なら None。(5) 一致無しも None。float 表記は `round` で int 化してから範囲判定。
  - `map_norm_to_abs(nx, ny, region) -> tuple[int, int]`（純）。丸め後にクランプする: `x = max(left, min(left + width - 1, left + round(nx/1000 * width)))`、y も同様。`width <= 0` または `height <= 0` のときは `(left, top)` を返す（ゼロ除算回避）。
  - `async ground_target(image_b64, *, instruction, region, model, base_url, api="openai", session=None, timeout_s=30.0, prompt=...) -> GroundResult | None`。呼び出し署名は `vlm_describe` に倣うが、**戻り型と失敗時の扱いは異なる**（`GroundResult | None` を返し、接続不可・タイムアウト・座標パース不可のいずれも None を返して例外を上げない）。`session=None` のときは**呼び出しごとに短命 `aiohttp.ClientSession` を内部生成して使い捨てる**。これは llama.cpp #17200（連続マルチモーダル要求の失敗）を踏まないための回避で、操作は要求駆動で頻度が低いため毎回新規セッションの開閉コストは許容する。
- `kotoha/operate/actions.py`（新・純）。操作語彙と意図パース。
  - `ActionRequest(kind, target="", text="", keys="", amount=0)`。kind は `"click" | "double_click" | "right_click" | "type" | "scroll" | "hotkey"`。target はグラウンディング指示に使う対象記述。`keys` は `"ctrl+s"` 形式の単一文字列（`keyboard.send` へそのまま渡す形）に統一する。
  - `parse_intent(text, *, config) -> ActionRequest | None`。発話から操作意図を取り出す。操作語が無ければ None（通常会話を素通し）。kind 判定と引数抽出を次に固定する。
    - 判定語: クリック系「クリック / 押して / 選んで / タップ」、開く系「開いて / ダブルクリック」、右クリック「右クリック」、入力「入力して / 打って / 〜と入力」、スクロール「スクロール / 上へ / 下へ / ページアップ / ページダウン」、ホットキー（後述の `hotkey_map` のキー語）。
    - `target`（click/double_click/right_click）: 判定動詞の直前の名詞句を取り、前後の助詞・空白を落とす。指示詞のみ（「ここ / そこ / あれ」等）や抽出失敗のときは `target=""` とし、その場合は発話原文をグラウンディング指示に使う。長さは 30 字で切る。
    - `text`（type）: 「『…』と入力 / 「…」と入力 / …と入力して」から本文を抜く。括りが無ければ「入力して」直前の語句を本文とする。本文が空なら None（操作なし）。
    - `amount`（scroll）: 上方向（上へ / ページアップ）を正、下方向を負へ写し、`amount` を ±5 にクランプ。単位はノッチ（actuator が `pyautogui.scroll` のクリック数へ写す）。
    - `keys`（hotkey）: `config.hotkey_map` を順に見て最初に一致した語のコンボ文字列を採用。未マップなら None（操作なし）。
  - `is_affirmative(text) -> bool` / `is_negative(text)`（純）。**否定優先**: パターン集合は `config` 化し、`is_negative` を先に評価する。否定語（「やめ / いや / ちがう / だめ / じゃない / しないで」等）を含むときは `is_affirmative` は False を返す。肯定語は「うん / はい / いいよ / お願い / そう」等。突き合わせは小文字化した部分一致。
- `kotoha/operate/policy.py`（新・純）。安全ポリシーの判定。
  - `is_destructive(action, *, destructive_keywords, hotkeys_always) -> bool`。`(action.target + " " + action.text)` を小文字化した文字列に破壊語を部分一致で含む、または `kind == "hotkey"` かつ `hotkeys_always`、で True（保守的に過剰確認側へ倒す）。`destructive_keywords` が空かつ `hotkeys_always=False` のときは確認機構が事実上無効化されるため、起動時に警告ログを出す。
  - `app_allowed(foreground_process, *, allowlist) -> bool`。`allowlist` が空なら **False（全拒否）**。非空なら、前面プロセスの **basename を小文字化した完全一致**がリストにあるときだけ True。`allowlist` のエントリはプラットフォーム別記法（Windows は `"chrome.exe"`、macOS/Linux はプロセス名）。前面プロセス名のなりすまし余地は v1 の許容範囲（ローカル単一ユーザー前提）とする。
- `kotoha/operate/actuator.py`（新・副作用、`pyautogui` / `keyboard` を遅延 import）。実行層。
  - `Actuator(*, dry_run, kill_hotkey, max_actions, backend=None)`。`backend is None`（実モード）のときだけ `pyautogui` を import して `FAILSAFE = True` を設定し、`keyboard` でグローバル kill ホットキーを登録して中断フラグへ配線する。`backend` を注入したときは `pyautogui` / `keyboard` を import せず fake で動く（テストはこの経路のみ使う）。`keyboard` の import 失敗やフック登録失敗（権限不足・依存欠如等）は捕捉し、案内付きでログして `kill_available=False` を立て、FAILSAFE のみの縮退運転に落とす（黙って kill 無効にしない）。
  - `execute(action, *, coords) -> bool`。中断フラグと動作上限を先に確認する。**`dry_run=True` は全 kind の実副作用を必ず抑止する**（kind 分岐の手前で弾く）。dry-run の可視化はログのみで、kind 別に「ここを押す」(click) / 「ダブルクリックする」/「右クリックする」/「『…』と入力する」(type) /「下へスクロール」(scroll) /「Ctrl+S を押す」(hotkey) を出す。実モードでは coords へ click / double_click / right_click、`type` は文字入力、`scroll` はノッチ量、`hotkey` は `keyboard.send(action.keys)`。例外・FAILSAFE・kill を全て握って False を返し、呼び出し側へ伝播させない。
  - `aborted() -> bool` / `kill_available() -> bool`。kill 状態と利用可否。`reset()` で解除。`close()` でフック解除。
- `kotoha/operate/operator.py`（新・統合の中核）。前段プロバイダとして orchestrator へ注入する。
  - `Operator(*, ground, capture_region, actuator, policy_cfg, get_foreground, stats=None, confirm_destructive=True, pending_ttl_s=60.0, clock=time.monotonic)`。`ground` は `ground_target` の partial（`functools.partial(ground_target, model=…, base_url=resolved_url, api=…, session=None, timeout_s=…, prompt=…)` のように構築。`session=None` で毎回新規セッション）、`capture_region` は `(image_b64, Region) | None` を返す callable、`get_foreground` は前面プロセス名を返す callable、`policy_cfg` は `is_destructive` / `app_allowed` へ展開する破壊語・hotkeys_always・allowlist を保持する。
  - `async handle(text, *, user_id) -> str | None`。前段の入口。注入用の文脈文字列を返す。操作意図が無ければ None。確認待ちを `self._pending[user_id]`（`(ActionRequest, timestamp)`、座標は持たない）で保持し、`pending_ttl_s` を過ぎた pending は handle 冒頭で破棄して `OperationStats` に計上する。orchestrator の直列化されたターン処理（1 ユーザー 1 ターンずつ）内でのみ呼ばれる前提で、スレッドセーフは要求しない。`user_id` が無い経路（None キー）でも pending は一意に保てる。戻り値の文言仕様は後述の §エラー処理の表に従う。
- `kotoha/operate/stats.py`（新・観測専用）。`OperationStats`。`PerceptionStats` と対称。加算条件を固定する: `intents`=`parse_intent` 非 None、`grounded`=`ground_target` が `GroundResult` を返した、`executed`=`execute` が True、`confirmed_pending`=確認待ちへ遷移、`refused`=否定で取りやめ、`expired`=pending 失効、`aborted`=kill 中断、`failures` は理由別 dict（capture / connect / timeout / parse / foreground / allowlist）。`avg_ground_ms` も持つ。`snapshot()` と `summary_line()`（例 `intents=3 grounded=2 exec=1 confirm=1 refused=0 aborted=0 fail=0`）を返す。スレッドセーフ、例外を投げない。
- `kotoha/operate/proof.py`（新・CLI）。`python -m kotoha.operate.proof "指示"`。プライマリをキャプチャし指示をグラウンディングして、固定書式で `[foreground] …` / `[region] left,top,w,h` / `[norm] nx,ny` / `[abs] x,y` / dry-run の「ここを押す」/ `[raw] <Holo2 応答原文>` / `COORDINATE_FORMAT: <観察した出力形式>` を表示する（Holo2 の 0〜1000 正規化を実機で裏取りするための目印）。`--arm` のときだけ実作動する。テスト可能な `run_proof` と実機結線の `main` に分ける（`screen/proof.py` と同型）。

既存への変更は小さく抑える。

- `kotoha/orchestrator.py`（改）。`__init__` に `operator=None` を足し（`api_search` / `screen_context` と同じ任意依存）、`handle_utterance` で `await self.operator.handle(text, user_id=user_id)` を呼ぶ（`api_search` とは `user_id` を渡す点だけ異なる。pending をユーザー別に成立させるため）。返った文字列を 1 行の system メッセージへ注入する。注入位置は他の文脈注入（時刻・画面）と並べ、operator が None を返すターンは何も注入しない。
- `kotoha/local_app.py`（改）。`operation_enabled` のとき `kotoha/operate/` のスタック（grounding 用 session / actuator / operator）を構築し、`ScreenContext` と前面情報取得を共有する。`memory_enabled` / `screen_perception_enabled` と同じ条件起動の流儀に合わせ、終了時に actuator を `close()` し `OperationStats.summary_line()` を表示する。
- `kotoha/screen/capture.py`（小改）。`MssCapturer` に `capture_with_region(self) -> tuple[str, Region] | None` を足す。縮小済み base64 とプライマリモニタの実矩形（mss の `monitors[1]` 由来の left/top/width/height）を返す。グラウンディングの座標写像に使う。既存 `capture()` は無変更。**操作機能のキャプチャは知覚の `screen_capture_backend` 設定によらず常に `MssCapturer`（プライマリ）を使う**。`DxcamCapturer` はゲーム全画面取得用で region 同定の経路を持たないため、操作 v1 の対象外（dxcam バックエンドでも操作は mss プライマリで撮る）。
- `kotoha/config.py`（改）と `.env.example`（改）。後述の設定項目を追加する。
- `kotoha/diagnostics.py`（改）。`diagnose_operation(config, *, session, ...)` を足し、grounding エンドポイント到達・`pyautogui`/`keyboard` import 可否・kill フック登録可否・dry-run 状態・前面取得可否を見る（`diagnose_screen` と同型）。`operation_kill_hotkey` が常用キー（Ctrl+C/Z/S/A 等や主要 OS ショートカット）と衝突する場合は警告する。
- `kotoha/llm/persona.py`（改）。「頼まれたら画面を操作できる。破壊的な操作は実行前に確認する。操作したら短く報告する。操作が失敗したときは必ずそれを伝える。頼まれていないのに勝手に操作しない」をシステムプロンプトに足す。

## 起動と制御フロー

operator は会話ターンの前段で動く。発話 1 回につき 3 経路のいずれかを通る。

**経路 A（無害・単ターン）**。`parse_intent` が無害な操作（リンクのクリック、フォーカス等）を返す。`app_allowed` を確認し、`capture_region` → `ground_target(instruction=target)` で座標を得る。`is_destructive` が False なので `actuator.execute` をその場で呼び、結果（dry-run なら「ここを押す」、実モードなら実行）を文脈へ注入する。LLM が「クリックしたよ」と短く語る。grounding と execute の間（数百 ms〜数秒）に画面が動くと座標は古くなりうるが、無害操作は大きく安定した UI を前提とし、確認は挟まない。信頼度しきい値による棄却は §未決の後続検討に紐づける。

**経路 B（破壊的・2 ターン握手）**。`is_destructive` が True かつ `confirm_destructive` のとき、`pending[user_id]` に `(ActionRequest, timestamp)` だけ保存し、実行はしない。「送信を求めている。実行前に確認する」を文脈へ注入し、LLM が「送信していい?」と聞く。次のターンでは **`is_negative` を先に評価**する。否定なら pending を消して「取りやめた」を注入。`is_affirmative` を満たすなら、**実行前に `app_allowed` を再評価**し（確認の間に前面アプリが許可外へ変わっていれば pending を破棄して「対象アプリが変わったため取りやめた」を注入）、許可されていれば**座標は保存していないので再キャプチャ・再グラウンディングして最新座標で実行**し、pending を消して結果を注入する。肯定でも否定でもない発話は pending を捨て、その発話を新しい意図として `parse_intent` し直す。pending は `pending_ttl_s`（既定 60 秒）を過ぎたら handle 冒頭で失効させ、古い「はい」が後から効かないようにする。

**経路 C（操作意図なし）**。`parse_intent` が None。operator は None を返し、注入はゼロで、会話は従来と一切変わらない。

座標は保存せず確認時に再グラウンディングするのは、確認の間に画面がスクロール等で動いていても誤クリックしないため。古い座標を握って後から実行する方が事故りやすい。

## 座標写像

`capture_with_region` がプライマリモニタを撮り、`(縮小済み base64, Region(left, top, width, height))` を返す。Holo2 は縮小画像上の正規化座標（0〜1000）を返す。縮小は等比なので正規化座標はモニタ実寸に対しても不変で、`abs = (left + nx/1000 * width, top + ny/1000 * height)` で絶対 OS 座標へ写像し、region 内へクランプする。PyAutoGUI には絶対 OS 座標を渡す。マルチモニタ間移動は本 spec の対象外で、プライマリのみ扱う。

## ルーティング層

知覚 Phase 1 の「ロール → エンドポイント対応表」に **grounding ロールを 1 つ足す**。対応表は base_url・API 様式・モデル名を持つ。grounding の既定配置は VII（Vulkan）の **llama-server で Holo2-8B GGUF**（OpenAI 互換）。`grounding_url` が空なら `vlm_perception_url`、それも空なら `ollama_url` の順でフォールバックする。Holo2-8B は 8B かつ thinking 由来で prefill が重いため、知覚 VLM とは別ポート・別インスタンスで立てるのが無難。実作動は要求駆動で頻度が低く、1 操作あたり数秒の grounding は許容できる。

## 設定項目

`kotoha/config.py` の `Config` に追加する。env の対応キーは `.env.example` に記す。

```python
# --- デスクトップ操作グラウンディング (docs/specs/2026-06-29-desktop-operation-grounding-design.md) ---
operation_enabled: bool = False              # 既定OFFのオプトイン
operation_dry_run: bool = True               # 既定は可視化のみ。OPERATION_DRY_RUN=false で実作動(arming)
operation_app_allowlist: tuple = ()          # 空=全拒否。許可する前面プロセス名 例 ("chrome.exe","code.exe")
operation_confirm_destructive: bool = True   # 破壊操作は2ターン音声確認
operation_destructive_keywords: tuple = (    # 対象/入力に含むと破壊的とみなす
    "送信", "削除", "消", "購入", "買", "注文", "支払", "送金",
    "投稿", "公開", "閉じ", "破棄", "リセット", "フォーマット", "アンインストール",
)
operation_destructive_hotkeys_always: bool = True  # hotkey は常に確認
operation_kill_hotkey: str = "ctrl+alt+q"    # グローバル中断キー。常用キー(Ctrl+C/Z/S/A 等)は避ける
operation_max_actions_per_command: int = 1   # 1発話=1操作
operation_pending_ttl_s: float = 60.0        # 破壊確認の保留がこれを過ぎたら失効
# 発話語→キーコンボ。parse_intent が最初に一致した語のコンボを hotkey として採用
hotkey_map: tuple = (("保存", "ctrl+s"), ("元に戻す", "ctrl+z"), ("コピー", "ctrl+c"), ("貼り付け", "ctrl+v"), ("全選択", "ctrl+a"))
# grounding(Holo2)エンドポイント。空なら vlm_perception_url→ollama_url の順でフォールバック
grounding_url: str = ""                       # 例 http://localhost:11436
grounding_model: str = "holo2-8b"
grounding_api: str = "openai"                 # Holo2 は OpenAI 互換が公式
grounding_timeout_s: float = 30.0             # 8B+thinking で prefill 重め
grounding_prompt: str = (
    "次の画面のスクリーンショットを見て、指示された UI 要素のクリック点を求めて。"
    "座標は画像に対して x, y それぞれ 0〜1000 で正規化した整数で 1 組だけ返す。"
)
```

`grounding_url` のフォールバックは `local_app` で `ground_target` の partial を組む時点で `config.grounding_url or config.vlm_perception_url or config.ollama_url` と解決する（知覚の describe partial と同型）。シングル GPU 環境でも既定のまま壊れず、VII を使うときだけ grounding を VII のサーバへ向ける。

`build_config`（`kotoha/config.py`）の env 取り込みも合わせて拡張する。`GROUNDING_URL` / `GROUNDING_MODEL` / `GROUNDING_API` は既存の文字列フィールド集合（`_ENV_STR_FIELDS`）へ、`OPERATION_ENABLED` / `OPERATION_DRY_RUN` は `SCREEN_PERCEPTION_ENABLED` と同じ bool 変換へ、`OPERATION_APP_ALLOWLIST` はカンマ区切りを tuple へ、`GROUNDING_TIMEOUT_S` / `OPERATION_PENDING_TTL_S` は float 変換で読む。`.env.example` には `OPERATION_ENABLED`・`OPERATION_DRY_RUN`・`OPERATION_APP_ALLOWLIST`・`GROUNDING_URL`・`GROUNDING_MODEL` などの上書きを追記する。

## 安全機構

実作動に至るまで多層で囲む。1 つ抜けても他で止まる。

| 層 | 機構 | 既定 | 説明 |
| --- | --- | --- | --- |
| 1 | オプトイン | `operation_enabled=False` | 既定 OFF。明示有効化したときだけ。 |
| 2 | dry-run / arming | `operation_dry_run=True` | 有効化しても既定は可視化のみ。`OPERATION_DRY_RUN=false` を明示して初めて実作動。 |
| 3 | アプリ allowlist | `operation_app_allowlist=()` | 空は全拒否。許可した前面アプリのときだけ操作。前面アプリは常にログ。 |
| 4 | 破壊操作の確認 | `operation_confirm_destructive=True` | 破壊的分類の操作は 2 ターン音声握手を必須。無害は即実行。 |
| 5 | グローバル kill | `operation_kill_hotkey="ctrl+alt+q"` | `keyboard` のグローバルフック。押下で in-flight 中止と以降拒否。 |
| 6 | FAILSAFE | 常時 ON | `pyautogui.FAILSAFE=True`。マウスを画面隅へ叩くと例外で中断。 |
| 7 | 動作上限 | `operation_max_actions_per_command=1` | 1 発話 1 操作。連鎖・ループ禁止。 |
| 8 | 非永続化 | — | スクショはメモリのみ、grounding 後破棄。残すのは座標と短い結果文だけ。 |
| 9 | best-effort 隔離 | — | operator・actuator は声ループへ例外を上げない。失敗は文脈文字列にして会話続行。 |

実作動には 3 つの明示設定が要る。`operation_enabled=True`（有効化）、`OPERATION_DRY_RUN=false`（arm）、`operation_app_allowlist` に対象アプリを列挙（許可）。どれかが欠ければ操作は起きない。

## プライバシー

既定で無効。有効化したときだけキャプチャと操作をする。スクリーンショットはディスクへ保存せずメモリ上で扱い、grounding へ渡したら破棄する。送信先はローカルの grounding VLM だけで、外部 API へは出さない。座標と短い結果文以外は残さない。

## エラー処理

操作は best-effort とする。`actuator` は FAILSAFE・kill・任意の例外を全て握って False を返し、声ループへ伝播させない。`Actuator.__init__` の `keyboard` import・フック登録失敗も捕捉し、`kill_available=False` の縮退運転（FAILSAFE のみ）に落として黙って無効化しない。Holo2 が thinking だけ返して座標が取れない場合も None 扱いで、操作は起きない。grounding サーバが落ちていれば操作は単に無効化され、会話と TTS は通常どおり動く。

`operator.handle` の戻り値は会話 LLM へ注入する文脈文字列で、ユーザーが「実行された／されなかった」を取り違えないよう失敗を明示する。

| 状況 | 戻り値 |
| --- | --- |
| 操作意図なし | `None`（注入しない） |
| 実行成功（無害・確認後） | `（検索ボタンをクリックした）` 等の実行報告 |
| dry-run 可視化 | `（dry-run: 検索ボタンを押すところ。実際には押していない）` |
| 確認要求（破壊的） | `送信を求めている。実行前に確認する` |
| 取りやめ（否定／アプリ変化） | `操作を取りやめた` / `対象アプリが変わったため取りやめた` |
| 失敗（理由別） | `[操作失敗] {理由}`。理由は キャプチャ失敗 / 接続失敗 / タイムアウト / 対象が見つからない / 許可外アプリ / 中止(kill) |

`handle` の分岐（擬似コード、docstring に置く）: pending を失効チェック → pending あり: `is_negative` なら取りやめ、`is_affirmative` なら `app_allowed` 再評価のうえ再 grounding して実行、それ以外は pending 破棄して下へ → `parse_intent` が None なら `None` → `app_allowed` 不可なら `[操作失敗] 許可外アプリ` → capture+ground、失敗は `[操作失敗] {理由}` → `is_destructive` なら確認要求（pending 保存）、無害なら execute して報告。各分岐で `OperationStats` を加算する。`persona.py` には「頼まれた操作が失敗したときは必ずそれを伝える」を足す。

## テスト

この環境（開発機・macOS）は **fake のみ**で通す。モデル DL・実 grounding・実作動・`pyautogui`/`keyboard` の実 import はしない。

ユニットテスト（既定実行 `-m "not integration"`、開発機で緑）。純ロジックと、fake 注入した副作用層を対象にする。

- `grounding.py`: `parse_ground_response`（thinking ブロック剥がし、`click(x,y)`/`(x,y)`/JSON、範囲外・複数組・float、失敗の None）、`map_norm_to_abs`（丸め後クランプ、width/height<=0 のガード）。
- `actions.py`: `parse_intent`（各操作語・target/text/scroll 抽出・hotkey_map 突き合わせ・未マップ None・None 素通し）、`is_affirmative` / `is_negative`（否定優先）。
- `policy.py`: `is_destructive`（破壊語の部分一致・hotkey）、`app_allowed`（空=全拒否、basename 小文字完全一致）。
- `actuator.py`: fake backend で、dry-run は全 kind がログのみで実入力が呼ばれない、実モードは backend が呼ばれる、kill で中止、動作上限、`backend` 注入時に実 import しない、kill 登録失敗時の縮退（`kill_available=False`）。
- `operator.py`: fake ground + actuator + foreground で、経路 A（無害単ターン）、経路 B（破壊 2 ターン握手・確認後の `app_allowed` 再評価・再グラウンディング）、経路 C（素通し）、allowlist 拒否、pending 破棄、pending 失効（TTL）、失敗時の `[操作失敗] {理由}` 文言。
- `stats.py`: `OperationStats` の計数・平均・`summary_line`。
- `config.py`: `build_config` が `OPERATION_*` / `GROUNDING_*` を bool・tuple・float へ正しく取り込む。

integration テスト（`@pytest.mark.integration` + テスト内 `pytest.importorskip`、rig のみ）。実 Holo2 で実画面の既知 UI をグラウンディングし、座標が妥当範囲に入ることを **dry-run で**確認する。実作動はテストせず proof CLI に委ねる。

proof CLI（rig・手動）。`python -m kotoha.operate.proof "その検索ボタンをクリック"` が前面アプリ・region・正規化/絶対座標・dry-run の「ここを押す」を表示する。`--arm` で初めて実作動。Holo2 の実座標出力形式（0〜1000 正規化の裏取り）もここで確認する。

## 受け入れ基準

設定で有効化し arm し allowlist を通したアプリで、つくよみに「その検索ボタンを押して」と頼むと、画面をキャプチャしてボタンの位置をグラウンディングし、その座標をクリックして「押したよ」と短く報告する。「送信して」のような破壊的操作は、まず「送信していい?」と確認し、肯定したときだけ最新座標で実行する。dry-run のときは実際には押さず、どこを押すかを示すだけ。許可リストに無いアプリ、無効、未 arm のときは操作しない。kill キーと画面隅 FAILSAFE でいつでも止まる。grounding やキャプチャが失敗しても会話は止まらない。1 発話につき操作は 1 回だけ。

## 未決・後続

- 操作語彙の拡張（ドラッグ、複数操作の連鎖、座標以外のスクロール対象指定）は本 spec の 1 発話 1 操作・基本語彙が実機で安定してから別 spec で扱う。
- Holo2 の実座標出力形式が 0〜1000 正規化でない場合（絶対 px や独自構造）の取り回しは proof CLI の実測で確定し、`parse_ground_response` に反映する。
- マルチモニタ間の操作、座標グラウンディングの信頼度しきい値による棄却は、プライマリ単体が固まった後に検討する。
- Phase 1 既知バグ（llama.cpp で Qwen3-VL 系が連続マルチモーダル要求に失敗する報告、issue #17200）は grounding でも踏みうる。要求ごとにセッションを立て直す回避を proof で確認する。
- 動的 GPU プランナ（搭載 GPU 列挙と主従自動割当）は知覚側の後続フェーズと共通の別 spec とし、grounding ロールも同じ対応表に載せる。
