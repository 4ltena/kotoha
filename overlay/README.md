# Kotoha overlay (SP1)

Kotoha のデスクトップ・オーバーレイ。透明・最前面・クリックスルーの Electron 窓に three.js + @pixiv/three-vrm で VRM を表示し、Python 側(SP2)の WebSocket から `state` と `mouth` を受けて状態と口パクを反映する。Python 無しでも単体で起動でき、その場合はキー操作のモックで動かせる。

## セットアップ

```powershell
cd overlay
npm install
```

VRM は `assets/sample.vrm` に置く。リポジトリには含めない(サイズとライセンスのため `.gitignore` 済み)。未配置でも起動はでき、青いキューブのプレースホルダが出る。VRoid Studio で書き出した `.vrm` などを置けばキャラが表示される。

## 起動

本番ビルドして起動するのが簡単。

```powershell
npm run build
npm start
```

開発中はホットリロードできる。ターミナルを2つ使う。

```powershell
npm run dev       # Vite 開発サーバ
npm run dev:app   # 別ターミナルで Electron を dev 起動
```

窓はクリックスルーなので、終了は起動したターミナルで Ctrl+C。キー `1`〜`4` で idle/listening/thinking/speaking を切り替えられる(モック)。

## テスト

純ロジック(config / mappings / ws-client)を vitest で検証する。描画は実行して目視で確認する。

```powershell
npm test
```

## electron のバイナリが入らないとき

`npm install` は通るのに起動時に `Electron failed to install correctly` が出ることがある。electron@30 同梱の `@electron/get` が新しい Node では本体 zip(約100MB)を無言で取り損ね、`node_modules/electron/dist` と `path.txt` が作られないのが原因。手動で取得して展開すると直る。

```powershell
cd overlay
$zip = "$env:TEMP\electron-v30.5.1-win32-x64.zip"
Invoke-WebRequest -Uri "https://github.com/electron/electron/releases/download/v30.5.1/electron-v30.5.1-win32-x64.zip" -OutFile $zip
Remove-Item -Recurse -Force node_modules\electron\dist -ErrorAction SilentlyContinue
Expand-Archive -Path $zip -DestinationPath node_modules\electron\dist -Force
"electron.exe" | Out-File -NoNewline -Encoding ascii node_modules\electron\path.txt
node_modules\.bin\electron --version
```

`(Get-Item $zip).Length` が約 1 億(100MB 超)なら本物が取れている。最後の `electron --version` がバージョンを返せば復旧。社内ネットなどで GitHub から取れない場合は `$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"` を設定してから取得する。

---

## English

Kotoha's desktop overlay. A transparent, always-on-top, click-through Electron window renders a VRM with three.js + @pixiv/three-vrm and reflects `state` and `mouth` from the Python side (SP2) over WebSocket. It also runs standalone without Python, driven by keyboard mock input.

Setup: `cd overlay && npm install`. Put a VRM at `assets/sample.vrm` (kept out of git for size and licensing; a placeholder cube shows when it is missing).

Run: `npm run build` then `npm start`, or for hot reload use two terminals with `npm run dev` and `npm run dev:app`. The window is click-through, so quit with Ctrl+C in the terminal. Keys `1`–`4` switch idle/listening/thinking/speaking. Tests: `npm test`.

If startup throws `Electron failed to install correctly` even though `npm install` succeeded, electron@30's bundled `@electron/get` failed to fetch the ~100MB binary on newer Node and left `node_modules/electron/dist` and `path.txt` missing. Fix it by downloading and extracting the binary manually with the PowerShell block above (Invoke-WebRequest the release zip, Expand-Archive into `node_modules/electron/dist`, write `path.txt`). If GitHub is unreachable, set `ELECTRON_MIRROR` first.
