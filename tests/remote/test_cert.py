import os

from kotoha.remote.cert import ensure_self_signed_cert


def test_cert_created_and_idempotent(tmp_path):
    d = str(tmp_path / "certs")
    cert, key = ensure_self_signed_cert(d)
    assert os.path.exists(cert) and os.path.exists(key)
    # 2回目は再生成せず同じパスを返す
    cert2, key2 = ensure_self_signed_cert(d)
    assert (cert, key) == (cert2, key2)
