"""リモート音声用の自己署名 TLS 証明書を用意する。

ブラウザの getUserMedia(マイク)は localhost 以外では HTTPS(セキュアコンテキスト)が
必須。LAN の他端末から使うため、自己署名証明書を生成して HTTPS/WSS を提供する。
証明書が無ければ生成し、(cert_path, key_path) を返す。
"""

import logging
import os

logger = logging.getLogger(__name__)


def ensure_self_signed_cert(cert_dir: str) -> tuple[str, str]:
    """cert_dir に cert.pem/key.pem を用意し、そのパスを返す。無ければ自己署名で生成。"""
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "cert.pem")
    key_path = os.path.join(cert_dir, "key.pem")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "kotoha-remote")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("generated self-signed cert at %s", cert_dir)
    return cert_path, key_path
