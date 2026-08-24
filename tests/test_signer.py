"""CAdES ``.p7m`` signing round-trip with an in-test self-signed PKCS#12."""
import datetime

import pytest

cryptography = pytest.importorskip("cryptography")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12
from cryptography.x509.oid import NameOID

from einvoice import P12Signer, sign_cades, sign_filename

XML = b'<?xml version="1.0"?><p:FatturaElettronica xmlns:p="x">test\r\ncontent</p:FatturaElettronica>'
PASSPHRASE = "segretissima"


def _make_p12(passphrase: str | None = PASSPHRASE) -> tuple[bytes, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IT"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Palestra Test SSD"),
        ]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    enc = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    p12 = pkcs12.serialize_key_and_certificates(b"test", key, cert, None, enc)
    return p12, cert


def test_sign_cades_attached_der_roundtrip():
    p12, cert = _make_p12()
    signed = sign_cades(XML, p12, PASSPHRASE)

    assert signed[:1] == b"\x30"  # DER SEQUENCE (not PEM/SMIME text)
    # Attached signature: the XML must be embedded verbatim (Binary option —
    # no MIME canonicalization, CRLF preserved).
    assert XML in signed
    # The signer certificate travels in the envelope.
    certs = pkcs7.load_der_pkcs7_certificates(signed)
    assert cert.serial_number in [c.serial_number for c in certs]


def test_sign_cades_accepts_path_and_no_passphrase(tmp_path):
    p12, _ = _make_p12(passphrase=None)
    path = tmp_path / "cert.p12"
    path.write_bytes(p12)
    signed = sign_cades(XML, path, None)
    assert XML in signed


def test_sign_cades_wrong_passphrase():
    p12, _ = _make_p12()
    with pytest.raises(ValueError, match="passphrase"):
        sign_cades(XML, p12, "sbagliata")


def test_sign_cades_empty_content():
    p12, _ = _make_p12()
    with pytest.raises(ValueError):
        sign_cades(b"", p12, PASSPHRASE)


def test_sign_filename():
    assert sign_filename("IT01234567890_00001.xml") == "IT01234567890_00001.xml.p7m"


def test_p12_signer_protocol():
    from einvoice import Signer

    p12, _ = _make_p12()
    signer = P12Signer(p12, PASSPHRASE)
    assert isinstance(signer, Signer)
    signed, fname = signer.sign(XML, filename="IT01234567890_00001.xml")
    assert fname == "IT01234567890_00001.xml.p7m"
    assert XML in signed
