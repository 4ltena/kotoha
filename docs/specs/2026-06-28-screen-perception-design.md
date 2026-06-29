# 画面知覚 Phase 1 — 設計

2026-06-28。kotoha につくよみの「画面を見る」能力を足す。マイクと同じ流儀で、画面を一定間隔でキャプチャしてローカルの VLM に渡し、得た要約を会話の文脈へ織り込む。本 spec は知覚のみを対象とし、デスクトップ操作は Phase 2、GPU の動的割当は Phase 3 に分ける。関連は [オーバーレイ設計](2026-06-26-overlay-design.md) と既存の API 検索プロバイダ（`kotoha/tools/`）。

## 方針

holo-desktop-cli は使わない。あのリポジトリで実際に画面を見て操作するのはクローズドな `hai-agent-runtime` バイナリで、Apache-2.0 で公開されているのはランタイムを起動して loopback で喋るだけの薄いクライアントと wire 契約 `hai-agent-api` に過ぎない。閉じたランタイムを拒むなら、駆動できる中身が残らない。よって **Apache-2.0 のモデルだけを使い、キャプチャと知覚のループは kotoha 側に自前で持つ**。

処理はすべて手元で完結させる。スクリーンショットは外部へ送らず、ローカルの VLM にだけ渡す。kotoha の「クラウドへ何も送らない」方針を画面知覚でも守る。

機能は既定で無効とし、設定で明示的に有効化したときだけ画面をキャプチャする。意図せず画面を読む事故を避けるためのオプトインとする。

## 採用部品とライセンス

ライセンスは Hugging Face のモデルカード等で実体を確認済み。すべて商用可の permissive を選ぶ。

| 用途 | 採用 | ライセンス | 備考 |
| --- | --- | --- | --- |
| 知覚 VLM（出荷時の既定・単一GPU） | Qwen3.5-4B（vision 対応） | Apache-2.0 | 会話と同じ `qwen3.5:4b` を使い回し、追加 VRAM・モデルスワップを避ける。VII 未接続の現状の既定 |
| 知覚 VLM（マルチGPU時の目標・任意） | Qwen3-VL-4B-Instruct | Apache-2.0 | 約 3.3GB(q4)。Ollama 公式タグ `qwen3-vl:4b`。VII に常駐させる場合に `vlm_perception_model` で上書き |
| 知覚 VLM（高精度・任意） | Qwen2.5-VL-7B-Instruct / Qwen3-VL-8B-Instruct | Apache-2.0 | 約 5.5GB(q4)。スワップ運用 |
| 操作グラウンディング（Phase 2） | Holo2-8B | Apache-2.0 | 座標出力に強い。Qwen3-VL-8B ベース |
| キャプチャ（通常） | mss | MIT | 速い。D3D 排他フルスクリーンは黒画になる弱点あり |
| キャプチャ（ゲーム・Windows） | dxcam-cpp | MIT | DXGI Desktop Duplication でゲーム画面も取得 |

サイズ別にライセンスが割れる罠がある。採用するのは上記の正確な variant に限る。非 permissive のため採用しないもの。Qwen2.5-VL-**3B**（Qwen Research、非商用）、MiniCPM-V-2.6（重み登録制）、Gemma 3（独自 Gemma 規約、gated）、LLaVA（Llama2 ＋ 学習データ規約）、Holo の **3B/30B/72B/235B**（研究・非商用）、Holo3-122B（クローズド・有料）。

## コンポーネント

新規パッケージ `kotoha/screen/` を置く。純ロジックと副作用を分け、重い依存（mss/dxcam）は `__init__` 内で遅延 import する。`sounddevice` を `speaker.py`/`mic.py` で遅延 import している既存の流儀に合わせる。

- `kotoha/screen/capture.py`（新）。`Capturer` 抽象と実装。`MssCapturer`(クロスプラットフォーム)、`DxcamCapturer`(Windows・ゲーム)。`capture()` は最新フレームを縮小して JPEG bytes と元解像度を返す。長辺の上限（既定 1024px）で VLM 負荷と VRAM スパイクを抑える。
- `kotoha/screen/detector.py`（新・主に純ロジック）。`GameDetector`。前面窓のフルスクリーン判定とプロセス名リストの併用でゲーム起動を判定する。窓矩形・前面プロセス名の取得だけ OS 依存にし、判定本体は純関数として注入で渡す。
- `kotoha/screen/state.py`（新・純）。`ScreenContext`。最新の画面要約、取得時刻、現在モード（normal/game-powersave/game-realtime）をスレッドセーフに保持する。読み手（orchestrator）と書き手（背景ループ）を疎結合にする。
- `kotoha/screen/perceiver.py`（新）。`ScreenPerceiver`。背景の async ループ。現在モードに応じた間隔でキャプチャし、VLM クライアントへ送り、結果を `ScreenContext` へ書く。声ループを絶対にブロック・失敗させない（best-effort）。
- `kotoha/llm/vlm_client.py`（新）。画像つきの推論を OpenAI 互換または Ollama の `/api/chat`（`images` に base64）で呼ぶ。`front_client.py` のストリーム実装と同型にし、エンドポイントとモデル名を引数で受ける。要約は短い日本語 1〜2 文に制約する（会話 LLM の `llm_num_predict=160` を圧迫しないため）。

既存への変更は小さく抑える。

- `kotoha/orchestrator.py`（改）。時刻・地点の文脈を system メッセージとして注入している箇所（現状 218〜251 行付近）に並べ、`ScreenContext` の最新要約を 1 行の system メッセージとして注入する。注入はキャッシュ読み取りのみで、ターンをブロックしない。
- `kotoha/llm/persona.py`（改）。「画面の話題は、聞かれたときや明らかに関係するときだけ自然に触れる。毎回実況しない」をシステムプロンプトに加える。天気と同じ扱いで、文脈は常に渡すが言及は必要時のみ。
- `kotoha/config.py`（改）と `.env.example`（改）。後述の設定項目を追加する。env の読み出しは既存どおり `local_app.py` 側で行い、`Config` の不変フィールドへ渡す。
- `kotoha/local_app.py`（改）。`ScreenPerceiver` と `GameDetector` を起動・停止のライフサイクルに組み込み、`ScreenContext` を orchestrator と共有する。`memory_enabled`/`overlay_enabled` と同じ条件起動の流儀に合わせる。

## ルーティング層

会話とそれ以外の LLM/VLM を別の推論バックエンドへ振り分ける。kotoha 本体はバックエンド非依存とし、**ロールからエンドポイントへの対応表**だけを見る。対応表は base_url、API 様式（ollama か openai 互換）、モデル名を持つ。

| ロール | 既定の配置 | バックエンド | モデル |
| --- | --- | --- | --- |
| chat（会話） | RTX 4080 | Ollama(CUDA) | `qwen3.5:4b` |
| vlm_perception（画面知覚） | Radeon VII | llama.cpp(Vulkan) | `qwen3-vl:4b` |
| memory_llm（記憶圧縮・要約） | Radeon VII | llama.cpp(Vulkan) | 既存 `memory_compress_model` |
| relationship（関係性分析） | Radeon VII | llama.cpp(Vulkan) | 既存 `relationship_model` |
| stt / tts | RTX 4080 | ローカル実行（LLM 外） | faster-whisper / GPT-SoVITS |

上はマルチGPU（4080＋VII）を目標とした配置。**出荷時の Phase 1 既定は VII 未接続を前提に単一GPUへ畳む**。`vlm_perception_url` / `aux_llm_url` が空なら知覚VLM・記憶・関係性はすべて 4080 の Ollama を指し、知覚VLM も会話と同じ `qwen3.5:4b`（vision 対応）を使い回す。VII を接続したら `.env` の `VLM_PERCEPTION_URL` / `AUX_LLM_URL` / `VLM_PERCEPTION_MODEL` で上の配置へ切り替える。

Phase 1 ではこの対応表を設定で静的に与える。供給源を差し替え可能な形にしておき、Phase 3 で自動検出器が同じ対応表を生成できるようにする。現状 `relationship_model` と `memory_compress_model` は会話と同じ `ollama_url` を暗黙に使っているため、各ロールに base_url を持たせて VII 側を指せるようにする。

## マルチGPU配置

実証環境は RTX 4080 と Radeon VII の 2 枚。役割で分ける。

- **RTX 4080（CUDA・リアルタイム）**。低遅延が要る感覚・思考・発話。STT、会話 LLM、TTS。
- **Radeon VII（Vulkan・非リアルタイム）**。遅延を許せる思考と視覚。記憶の圧縮・要約、関係性分析、通常モードの知覚 VLM。VII 未接続の現状ではこれらも 4080 の Ollama に同居し、知覚 VLM は会話と同じ `qwen3.5:4b` を使い回す。

Radeon VII は gfx906 で ROCm の公式サポートから外れており、Windows では ROCm が実質使えない（HIP SDK のサポート表で gfx906 は Unsupported、Ollama の ROCm パスも gfx906 を弾いて CPU へフォールバックする）。よって VII は **Vulkan** で動かす。Vulkan はベンダ非依存で gfx906 に動作実績がある。

VII 側は別プロセス・別ポートの Vulkan サーバを OpenAI 互換エンドポイントとして立てる。最短は **LM Studio**（Windows で Vulkan が既定動線、`:1234/v1`、VLM と要約モデルを 1 サーバに同居させ `model` で切替）。最新の Qwen3-VL を確実に使うなら **llama.cpp の llama-server（Vulkan ビルド）**で、画像入力は `--mmproj`、`/v1/chat/completions` に base64 data URI で渡す。Ollama も 2025-11 に Vulkan 対応したが experimental かつ VLM 実績が薄いため VII 本命にはしない。

ルーティングは 2 プロセス構成にする。4080 は Ollama/CUDA を `:11434` で動かし `OLLAMA_VULKAN=0` で Vulkan を掴ませない。VII は上記 Vulkan サーバを別ポートで動かす。混在環境では 4080 も VII も Vulkan デバイスとして列挙され順序が保証されないため、`llama-server --list-devices` で index を確認し `GGML_VK_VISIBLE_DEVICES` で VII を明示ピン留めする。kotoha 本体は base_url を VII のサーバへ向けるだけで、サーバ実装の差は意識しない。

知覚 VLM と記憶系 LLM が VII に載るため、4080 は会話パイプライン（STT ＋ 会話 LLM ＋ TTS で約 8GB 規模）に専念できる。会話 LLM を `qwen3.5:9b` に上げる場合は 4080 の余裕が減るため、知覚を使う構成では 4b を既定とする。

## 動作モード

- **通常モード**。mss で一定間隔にキャプチャする（既定 4 秒、設定可変）。縮小のうえ知覚 VLM へ送り、最新要約を更新する。
- **ゲームモード**。ゲーム起動を検知したら自動で切り替える。挙動は設定で 2 択。
  - **省力型**。会話以外の LLM 処理（記憶の圧縮・要約、関係性分析）と画面知覚を停止し、全体を静めて会話の即応性を確保する。
  - **リアルタイム型**。知覚を高頻度化し（既定 0.5 秒、設定可変）、画面状況を逐次把握する。Windows では dxcam でゲーム画面を取得する。VLM 推論は VII で回し、4080 をゲームに残す。VII が追いつかない場合に 4080 へ寄せる設定も持つ。なお実効周期は画像の prefill に律速される。VII の Vulkan では画像由来 2000〜4000 トークンの prefill に概ね 2〜4 秒かかるため、設定間隔はあくまで下限であり、実際はそれ以上空く。リアルタイム型では解像度を下げて画像トークンを減らし prefill を短縮する。

頻度、ゲームモードの 2 択、検出方式、ロール別エンドポイントは、いずれも設定で変更できる。

ゲーム検出は前面窓のフルスクリーン判定を基本とし、設定のプロセス名リストで補正する。フルスクリーン判定だけだと全画面動画なども拾うため、リストで誤検知と取りこぼしを抑える。

## データフロー

通常モードの 1 サイクル。背景ループがキャプチャ（mss）→ 縮小 → 知覚 VLM へ送信 → 短い日本語要約を受信 → `ScreenContext` を更新。会話ターンでは orchestrator が `ScreenContext` の最新要約を読み、時刻・地点と並べて system メッセージへ注入する。注入は非ブロッキングで、要約が空または古すぎる場合は注入しない。

モード切替。`GameDetector` が前面窓とプロセスを監視し、ゲーム起動・終了で `ScreenContext` のモードを変える。`ScreenPerceiver` は次サイクルからモードに応じた間隔とキャプチャ実装へ切り替える。省力型では知覚ループと記憶系・関係性のジョブを止める。

## 設定項目

`kotoha/config.py` の `Config` に追加する。env の対応キーは `.env.example` に記す。

```python
# --- 画面知覚 (docs/specs/2026-06-28-screen-perception-design.md) ---
screen_perception_enabled: bool = False        # 既定OFFのオプトイン
screen_capture_backend: str = "mss"            # "mss" | "dxcam"(Windows・ゲーム)
screen_capture_max_long_edge: int = 1024       # 送信前の縮小上限(長辺px)
screen_normal_interval_s: float = 4.0          # 通常モードのキャプチャ間隔
screen_game_mode: str = "powersave"            # "powersave" | "realtime"
screen_game_realtime_interval_s: float = 0.5   # リアルタイム型の間隔
screen_summary_max_age_s: float = 30.0         # これより古い要約は会話へ注入しない
# ゲーム検出
screen_game_detect_fullscreen: bool = True     # 前面窓フルスクリーン検知
screen_game_process_names: tuple = ()          # 補正用のプロセス名リスト
screen_game_poll_s: float = 2.0                # ゲーム検出のポーリング間隔
# 知覚VLM のエンドポイント(VII を指す。空なら ollama_url)
vlm_perception_url: str = ""                    # 例 http://localhost:11435
# 出荷時の既定は会話と同じ qwen3.5:4b(vision対応)を単一GPUで使い回す。VII の専用VLMを
# 使う場合は qwen3-vl:4b 等へ上書きする。
vlm_perception_model: str = "qwen3.5:4b"
vlm_perception_api: str = "openai"             # "openai" | "ollama"
vlm_perception_timeout_s: float = 20.0
vlm_perception_prompt: str = (
    "次の画面のスクリーンショットを見て、いま何が映っているかを日本語で1〜2文、"
    "簡潔に説明して。固有名詞やUIの文字があれば拾う。推測は最小限に。"
)
# 非リアルタイムLLM のエンドポイント(VII を指す。空なら ollama_url。memory/relationship 用)
aux_llm_url: str = ""                           # 例 http://localhost:11435
```

`vlm_perception_url` と `aux_llm_url` は空文字なら `ollama_url` へフォールバックする。これでシングルGPU環境は既定のまま動き、VII を使うときだけ各エンドポイントを VII のサーバへ向ける。`.env.example` には接続先の上書き（`VLM_PERCEPTION_URL`、`AUX_LLM_URL` など）を追記する。

## プライバシー

既定で無効。有効化したときだけキャプチャする。スクリーンショットはディスクへ保存せずメモリ上で扱い、VLM へ渡したら破棄する。送信先はローカルの VLM だけで、外部 API へは出さない。`ScreenContext` に残すのは短い要約テキストのみとし、画像は保持しない。

## エラー処理

知覚は best-effort とする。キャプチャ失敗、VLM 接続不可、タイムアウトのいずれでも、最新要約を更新しないだけで会話ループは止めない。VII のサーバが落ちていれば知覚は単に無効化され、会話と TTS は通常どおり動く。dxcam が排他フルスクリーンを取得できず黒画を返す場合は、要約を更新せず、必要ならボーダレス窓を促すログを出す。

## テスト

`detector.py` の判定本体、`state.py` の `ScreenContext`、`capture.py` の縮小・エンコード、`vlm_client.py` の要約整形は純ロジックとして pytest で検証する。窓矩形・前面プロセス取得・実キャプチャ・VLM 通信は OS とサービスに依存するため、`@pytest.mark.integration` ＋ 各テスト内 `pytest.importorskip` とし、既定実行は `-m "not integration"` から外す。既存のテスト方針に合わせ、ユニットテストは画面ハードや外部サービスなしで通す（fake 注入）。

## 受け入れ基準

設定で有効化すると、つくよみが現在の画面内容を踏まえて会話できる。普段は数秒に一度の低頻度キャプチャで、画面の話題は聞かれたときや関係するときだけ自然に出る。ゲームを起動すると自動でゲームモードへ切り替わり、省力型では会話以外の処理が止まり、リアルタイム型では高頻度に画面を把握する。頻度・モード・検出方式・接続先は設定で変えられる。知覚 VLM は Radeon VII（Vulkan）で動き、4080 の会話経路を妨げない。VLM やキャプチャが失敗しても会話は止まらない。

## 未決・後続

- **Phase 2（操作）**。Holo2-8B のグラウンディングと PyAutoGUI ＋ keyboard（グローバル kill スイッチ）で、キャプチャ → 次アクション座標 → 実行のループを作る。アプリ allowlist、破壊的操作の確認、FAILSAFE などの安全機構を必須とする。別 spec。
- **Phase 3（動的 GPU プランナ）**。搭載 GPU を列挙（NVIDIA は NVML、全ベンダは Vulkan 列挙）し、能力を分類（CUDA / ROCm 対応 AMD / ROCm 非対応 AMD は Vulkan / Intel は Vulkan）したうえで、主（リアルタイム）と従（非リアルタイム）を自動割当し、ルーティング対応表を生成・必要ならサーバを起動する。手動上書きも残す。別 spec。
- 真の排他フルスクリーンは dxcam でも取得できない場合があり、その扱いは実証で詰める。
- **既知バグ（要監視）**。llama.cpp で Qwen3-VL が連続2回目のマルチモーダル要求に失敗する報告がある（issue #17200、`/slots/reset` が 501）。数秒ごとに画像を送り続ける知覚ループはこれを踏みやすい。新しいビルドを使い、必要なら要求ごとにスロット/セッションを作り直す。LM Studio・KoboldCpp も内部は llama.cpp なので同根の挙動に注意する。
- VII の Vulkan サーバ構成は調査で確定済み。Qwen3-VL-4B GGUF は Q4_K_M 約 2.5GB ＋ mmproj-F16 約 0.84GB で、KV と画像トークン込みでも Q4 で概ね 4〜6GB に収まる（VII 16GB に余裕）。スループットは Vulkan で 7B Q4 が pp 約 1000 t/s・tg 約 100 t/s の実測（Linux 値、Windows は下振れしうる）。NVIDIA と AMD のドライバ同居は動作するが公式推奨ではないため、不調時はまず一方を完全削除して切り分ける。Vulkan には両 ICD が必要。
