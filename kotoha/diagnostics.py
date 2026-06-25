"""ローカル環境の事前疎通診断 CLI。

声データ(GPT-SoVITS 参照音声)が無くても、MVP 起動に必要な環境が整っているかを
確認するための軽量ツール。`python -m kotoha.diagnostics` で実行する。

- Ollama の稼働 + 設定モデル(config.ollama_model)のインストール有無
- GPT-SoVITS サーバの到達性
- (任意)音声入出力デバイス一覧([local] extra=sounddevice 導入時のみ)
"""

import asyncio
import logging

import aiohttp

from kotoha.config import Config
from kotoha.health import check_local_services

logger = logging.getLogger(__name__)


async def list_ollama_models(session, *, ollama_url: str) -> list:
    """Ollama /api/tags からインストール済みモデル名一覧を返す。接続不可なら []。"""
    try:
        async with session.get(f"{ollama_url}/api/tags") as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
    except aiohttp.ClientError:
        return []
    return [m.get("name", "") for m in data.get("models", [])]


def model_present(models: list, wanted: str) -> bool:
    """wanted モデルがインストール済みか。タグ未指定なら同名ファミリの有無で判定。"""
    if wanted in models:
        return True
    if ":" not in wanted:
        return any(m.split(":", 1)[0] == wanted for m in models)
    return False


async def diagnose(config, *, session) -> dict:
    """サービス疎通 + 設定モデルの存在を集約して返す。"""
    services = await check_local_services(
        session, ollama_url=config.ollama_url, gptsovits_url=config.gptsovits_url
    )
    models = await list_ollama_models(session, ollama_url=config.ollama_url)
    return {
        "ollama": services["ollama"],
        "gptsovits": services["gptsovits"],
        "model": config.ollama_model,
        "models": models,
        "model_present": model_present(models, config.ollama_model),
    }


def format_report(result: dict) -> str:
    """診断結果を人間可読のレポート文字列にする。"""
    lines = [f"[ollama]    {'OK' if result['ollama'] else 'DOWN'}"]
    if result["ollama"]:
        if result["model_present"]:
            lines.append(f"[model]     '{result['model']}': present")
        else:
            lines.append(
                f"[model]     '{result['model']}': MISSING "
                f"(run: ollama pull {result['model']})"
            )
    lines.append(f"[gptsovits] {'OK' if result['gptsovits'] else 'DOWN'}")
    return "\n".join(lines)


def list_audio_devices(sd=None):
    """音声デバイス一覧を返す([local] extra=sounddevice 必須)。"""
    if sd is None:
        import sounddevice as sd  # 遅延 import(未導入環境では呼び出し側が握る)
    return sd.query_devices()


async def run_diagnostics(config: Config) -> int:
    """疎通診断を実行してレポートを表示し、終了コードを返す(0=準備OK)。"""
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        result = await diagnose(config, session=session)
    print(format_report(result))

    print("\n[audio devices]")
    try:
        print(list_audio_devices())
    except Exception as e:
        print(f"取得不可: {e}([local] extra=sounddevice 未導入の可能性)")

    ok = result["ollama"] and result["gptsovits"] and result["model_present"]
    print("\n=> 準備OK" if ok else "\n=> 未充足の項目があります(上記を確認してください)")
    return 0 if ok else 1


def main() -> None:
    import sys

    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(run_diagnostics(Config())))


if __name__ == "__main__":
    main()
