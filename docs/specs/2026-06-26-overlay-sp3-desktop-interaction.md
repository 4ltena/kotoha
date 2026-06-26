# デスクトップ・オーバーレイ SP3 — デスクトップ干渉 設計

2026-06-26。オーバーレイ (SP1/SP2) に、ドラッグ移動、自律徘徊、簡易物理、タスクバー着地を加える。対象はプライマリモニタのみで、SP1 の上に積む。マルチモニタ移動とお触り反応 (SP4) は後続とする。関連: [SP1+SP2 設計](2026-06-26-overlay-design.md)。

## 方針

窓モデルは**小さな移動ウィンドウ**を採る。キャラ大の透明窓を画面上で動かし、歩行も物理もドラッグも窓の移動として表現する。スクリーン座標と 3D の写像が不要になり、当たり判定は窓ローカルの矩形判定に落ちる。

論理位置と物理、徘徊は **renderer が単一の源**として保持し、毎フレーム窓へ反映する。`main.js` は窓と IPC の薄いシムに留める。

## クリックスルーの切替

窓は既定でクリックスルー (`setIgnoreMouseEvents(true, { forward: true })`)。`forward: true` によりクリックスルー中も `mousemove` が renderer に届く。renderer はカーソルがキャラの矩形内かを判定し、内側なら `setInteractive(true)` を要求して操作を受け、外側なら `setInteractive(false)` で背面へ素通しする。

## コンポーネント

- `overlay/main.js` (改): 透明・枠なし・最前面の小窓を維持。IPC を追加する。`overlay:getDisplay`(作業領域と現在 bounds を返す)、`overlay:setPosition`(窓移動)、`overlay:setInteractive`(`setIgnoreMouseEvents` 切替)。
- `overlay/preload.js` (改): `contextBridge` で `window.overlay = { getDisplay, setPosition, setInteractive }` を公開する。
- `overlay/renderer/physics.js` (新・純): 位置と速度の積分、重力、床クランプ、放り投げ初速。
- `overlay/renderer/walker.js` (新・純): idle と walk の状態機械。接地・非ドラッグ時にたまに目標 x を選び歩く。向きを返す。乱数は注入する。
- `overlay/renderer/hit-test.js` (新・純): 点が矩形内かの判定。
- `overlay/renderer/interaction.js` (新): ポインタ配線。ホバー判定、ドラッグ開始・移動・終了、放り投げ用のサンプル記録。
- `overlay/renderer/main.js` (改): 論理位置を保持し、毎フレーム physics と walker を更新して `overlay.setPosition` で窓へ反映する。VRM を進行方向へ向け、歩行とアイドルを切り替える。SP2 の状態とも協調する。

## データフロー（1フレーム）

ドラッグ中はカーソルに追従する。非ドラッグ時は、接地かつ idle なら walker が水平移動を与え、空中なら physics が重力で落下させて床で接地する。結果の位置を `overlay.setPosition` で窓へ送る。`mousemove` が届くたびにキャラ矩形との当たりを判定し、`setInteractive` を切り替える。`mouseup` では直近のドラッグサンプルから放り投げ初速を求め、物理へ渡す。

## 床と座標

床は `getDisplay()` の `workArea` の下端から窓高を引いた y とする。これによりタスクバーの上に立つ。水平の可動域は `workArea` の左端から右端マイナス窓幅までとする。位置はスクリーンピクセルで扱う。

## SP2 との協調

WS の `state` と `mouth` は従来どおり表情と口パクへ反映する。`state` が `speaking` の間は徘徊を止めて正面を向く。物理とドラッグは `state` に関わらず動作する。

## エラー処理

IPC とオーバーレイ機能は best-effort とする。`getDisplay` 失敗時は妥当な既定（プライマリ解像度の推定）にフォールバックし、声ループや描画を止めない。

## テスト

`physics.js` / `walker.js` / `hit-test.js` は純ロジックとして vitest で検証する。重力積分と床クランプ、放り投げ初速の算出、idle と walk の遷移と目標選択、矩形内外の判定を対象とする。窓移動、クリックスルー切替、ドラッグ、描画は実機で目視確認する。

## 受け入れ基準

キャラがプライマリ画面の作業領域下端（タスクバー上）に立ち、自律的に左右へ歩く。キャラを掴んでドラッグでき、離すと重力で落下して着地する。投げると初速がのって飛ぶ。キャラの上だけ操作を受け、それ以外はデスクトップへクリックが素通しする。SP2 を併用すると、発話中は徘徊を止めて表情と口パクが反映される。

## 未決・後続

マルチモニタ間の移動、壁登りやぶら下がり、お触りとクリック反応 (SP4) は本 spec の対象外とする。
