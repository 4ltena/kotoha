# 画面要約の品質刷新 — 設計

2026-06-29。画面知覚 Phase 2 の観測を踏まえ、知覚ループの無駄な再要約を減らし、要約にアプリ文脈を足す。設計の正は本書、知覚の土台は [Phase 1 設計](2026-06-28-screen-perception-design.md) と [Phase 2 設計](2026-06-29-screen-perception-phase2-design.md)。

## 動機

現状 `ScreenPerceiver.tick` は base64 の**完全一致**で重複を判定する(`kotoha/screen/perceiver.py` の `image_b64 == self._last_capture_b64`)。このため、カーソルの点滅・時計の秒更新・わずかなアニメーションなど、会話に無関係な微小変化でも毎サイクル重い VLM を呼ぶ。Phase 2 の `PerceptionStats` で captures に対する describes 比が高止まりするのはこれが原因になりうる。また要約は素の1〜2文で、どのアプリ・ウィンドウを見ているかの文脈が落ちる。

## 方針

二つの独立した改善を入れる。どちらも best-effort を崩さず、新規依存を増やさない。

- **Part A 知覚ハッシュ変化検出**。完全一致を perceptual hash(difference hash)の距離判定へ置換し、閾値以下の微小変化では VLM を呼ばない。
- **Part B アプリ文脈付き要約**。要約と一緒に capture 時の前面アプリ名を保持し、会話への注入に添える。VLM の出力形式は素のまま保ち、TTS 汚染を避ける。

JSON 構造化要約や要素単位の構造化は本フェーズの対象外とする。注入と TTS の複雑化を避け、観測で必要が定量的に見えてから別フェーズで扱う。

## Part A: 知覚ハッシュ変化検出

新規 `kotoha/screen/phash.py`(純関数、PIL と numpy のみ。新規依存なし)。

- `dhash(image, hash_size: int = 8) -> int`。PIL.Image をグレースケール化し `(hash_size+1, hash_size)` へ縮小、横方向の隣接画素の大小比較で `hash_size*hash_size` ビットの整数を作る。difference hash は明度シフトに頑健で、UI の微小変化を吸収する。
- `hamming(a: int, b: int) -> int`。2つのハッシュのビット差。`bin(a ^ b).count("1")`。
- `dhash_b64(image_b64: str) -> int`。base64 JPEG をデコードして `dhash` を返す。デコード失敗時は例外を上げず呼び出し側が握れる形にはしない(純関数。呼び出し側 perceiver が try で囲む)。

`ScreenPerceiver` の変更。

- `__init__` に `change_threshold: int = 0` を足す。`_last_capture_b64` を `_last_hash`(int か None)へ置き換える。
- `tick` の完全一致ブロックを置換する。capture 後に `h = dhash_b64(image_b64)` を計算し、`self._last_hash is not None and hamming(h, self._last_hash) <= self._change_threshold` のとき VLM を呼ばず `touch()` して skip を記録する。要約を更新したら `self._last_hash = h` を保存する。dhash の計算自体が失敗したら(壊れたフレーム等)その回は skip 扱いで安全側に倒す。
- 設定 `screen_change_hash_threshold: int = 4` を `Config` に足し、`local_app` が perceiver へ渡す。0 なら従来同等(ほぼ完全一致)に近く、上げるほど鈍くなる。

`PerceptionStats` は無変更で流用する(skip は既存の `record_skip`)。変化量の数値記録は本フェーズでは足さない(観測の必要が出てから)。

## Part B: アプリ文脈付き要約

`ScreenContext` の変更。

- `set_summary(text: str, app: str = "") -> None`。要約と同時に `app`(前面アプリ名)を保持する。`app` 既定 "" で後方互換。
- `get_app() -> str`。有効な最新要約があるときだけ `app` を返す(要約が無効・期限切れなら "")。`get_summary` と同じ有効性判定に従う。

`ScreenPerceiver` の変更。

- `__init__` に `get_foreground=None` を足す。`get_foreground` は前面アプリ名を返す callable(注入)。
- `tick` の要約更新時に、`app = self._get_foreground() if self._get_foreground else ""` を取り、`set_summary(summary, app=app)` で渡す。`get_foreground` が例外を投げても要約更新は止めない(app="" にフォールバック)。

`kotoha/orchestrator.py` の変更。

- 画面要約の注入を、app があれば `【画面の様子】(アプリ: <app>)\n<summary>` の形へ拡張する。app が空なら従来どおり `【画面の様子】\n<summary>`。注入は非ブロッキングのキャッシュ読み取りのまま。

`kotoha/local_app.py` の変更。

- perceiver 構築に `change_threshold=config.screen_change_hash_threshold` と `get_foreground=lambda: (get_foreground_info() or {}).get("process", "")` を渡す。既存のキャプチャ・知覚配線に並べる。

## データフロー

通常モードの 1 サイクル。背景ループがキャプチャ → `dhash_b64` でハッシュ化 → 直近ハッシュとの hamming 距離が閾値以下なら VLM を呼ばず `touch()` して skip、超えれば VLM へ送って要約を受信し、前面アプリ名と一緒に `set_summary(summary, app)` で保存。会話ターンでは orchestrator が要約とアプリ名を読み、`【画面の様子】(アプリ: <app>)` の形で注入する。

## エラー処理

best-effort を維持する。`dhash_b64` のデコード失敗・`get_foreground` の例外のいずれも、要約を更新しないか app を空にするだけで会話ループは止めない。VLM・キャプチャの失敗時の挙動は Phase 1 から不変。

## テスト

`phash.py` は純ロジックとして pytest で検証する。同一画像 → 距離 0、横一列にずらした微差 → 小さい距離、白黒の大きく違う画像 → 大きい距離、`dhash_b64` が縮小済み JPEG を正しくデコードしてハッシュ化すること。`ScreenPerceiver` は fake capturer/describe で、閾値以下の微差フレームで VLM を呼ばずに skip、閾値超で describe を呼ぶこと、要約更新時に `get_foreground` の値が `set_summary` へ渡ることを検証する。`ScreenContext` は `set_summary(text, app)` の保持と `get_app` の有効性判定を検証する。`orchestrator` は app 付き要約が `(アプリ: ...)` 形式で注入されることを検証する。いずれも GPU・実画面・外部サービスなしで通す(fake 注入)。実 dhash・実キャプチャは integration 不要(純ロジックは fake 画像で足りる)。

## 受け入れ基準

知覚ループは、画面に意味のある変化があったときだけ VLM を呼び、カーソル点滅や時計更新のような微小変化では再要約しない。閾値は設定で変えられる。会話に注入される画面要約には、見ているアプリ名が添えられる(取得できたとき)。既存の知覚・会話・ゲームモードの挙動は不変で、画面知覚を無効にしている場合は何も変わらない。

## 未決・後続

- JSON・要素単位の構造化要約は、本フェーズの観測で必要が定量化されてから別 spec で扱う。
- dhash の閾値の最適値は実機の stats(skip 率)を見て調整する。固定既定 4 は出発点。
- ウィンドウ**タイトル**(プロセス名より具体的)取得は OS 依存が増えるため後続。本フェーズは前面プロセス名に留める。
