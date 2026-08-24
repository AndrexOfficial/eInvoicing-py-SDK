"""CAdES-style ``.p7m`` signing of FatturaPA XML with a PKCS#12 certificate.

SdI accepts FatturaPA either unsigned (via some intermediari) or signed
CAdES-BES (``.p7m``, DER PKCS#7 SignedData with the XML embedded — *attached*
signature) / XAdES-BES. This module produces the attached PKCS#7 SignedData
with SHA-256 using the ``cryptography`` library's PKCS7 API and a PKCS#12
(``.p12``/``.pfx``) certificate + private key.

Honest limitation
-----------------
``cryptography``'s :class:`PKCS7SignatureBuilder` emits standard CMS/PKCS#7
SignedData with the ``contentType`` / ``messageDigest`` / ``signingTime`` /
SMIME-capabilities authenticated attributes. **Full CAdES-BES per ETSI
EN 319 122-1 additionally requires the ``signing-certificate-v2`` (ESS)
signed attribute**, which the builder does not currently expose. In practice
SdI's validator accepts well-formed attached PKCS#7/CMS signatures made with
a *qualified* certificate, but for guaranteed ETSI compliance (and for
conservazione a norma) use an accredited signing service/HSM — or let the
conservazione/transmission provider (e.g. Aruba) re-sign. The certificate
must be a **qualified electronic-signature certificate** (firma qualificata,
eIDAS) issued to the person/entity signing the invoices; an ordinary TLS
certificate is not legally valid for SdI.

``cryptography`` is an optional dependency (``pip install einvoice[signing]``)
and is imported lazily so the core package stays zero-dependency.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .errors import SigningUnavailable

__all__ = [
    "sign_cades", "sign_filename", "P12Signer",
    "SigningCertificate", "inspect_p12",
]


def sign_filename(name: str) -> str:
    """``IT01234567890_00001.xml`` → ``IT01234567890_00001.xml.p7m``."""
    return f"{name}.p7m"


def _load_p12(p12: bytes | str | os.PathLike, passphrase: str | bytes | None):
    """Load (private_key, certificate, additional_certs) from P12 bytes or path."""
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
    except ImportError as exc:  # pragma: no cover
        raise SigningUnavailable(
            "la firma CAdES richiede 'cryptography': pip install einvoice[signing]"
        ) from exc

    p12_bytes = Path(p12).read_bytes() if isinstance(p12, (str, os.PathLike)) else p12
    pw = passphrase.encode("utf-8") if isinstance(passphrase, str) else passphrase
    if pw == b"":
        pw = None
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(p12_bytes, pw)
    except Exception as exc:
        raise ValueError(f"PKCS#12 non valido o passphrase errata: {exc}") from exc
    if key is None or cert is None:
        raise ValueError("il PKCS#12 non contiene chiave privata + certificato")
    return key, cert, extra or []


@dataclass(frozen=True)
class SigningCertificate:
    """What a PKCS#12 archive actually contains, without signing anything.

    A signing certificate has an expiry date, and a signature made with an
    expired one is refused downstream while looking perfectly fine locally —
    the configuration was valid the day it was saved. Anything that stores a
    P12 should read :attr:`valid_until` and warn before that day arrives.
    """

    subject: str
    issuer: str
    serial_number: str
    valid_from: date
    valid_until: date

    def is_expired(self, *, on: date | None = None) -> bool:
        return (on or date.today()) > self.valid_until

    def is_not_yet_valid(self, *, on: date | None = None) -> bool:
        return (on or date.today()) < self.valid_from

    def days_until_expiry(self, *, on: date | None = None) -> int:
        """Negative once expired."""
        return (self.valid_until - (on or date.today())).days

    def expires_within(self, days: int, *, on: date | None = None) -> bool:
        """True when renewal should already be under way (expired counts)."""
        return self.days_until_expiry(on=on) <= days


def _as_date(value: datetime) -> date:
    """Certificate validity is UTC; a local-time reading is off by a day."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).date()


def inspect_p12(
    p12: bytes | str | os.PathLike,
    passphrase: str | bytes | None = None,
) -> SigningCertificate:
    """Open a PKCS#12 archive and describe its certificate. Signs nothing.

    This is the supported way to validate signing credentials when they are
    configured, rather than discovering at the first real invoice that the
    passphrase was wrong::

        try:
            cert = inspect_p12(archive, passphrase)
        except SigningUnavailable:
            ...   # cannot check here; the extra is not installed
        except ValueError as exc:
            ...   # the archive or the passphrase is wrong — refuse it

        if cert.expires_within(30):
            warn(f"il certificato scade il {cert.valid_until}")

    :raises ValueError: the archive is not a valid PKCS#12, the passphrase is
        wrong, or it carries no private key + certificate pair.
    :raises SigningUnavailable: the ``[signing]`` extra is not installed.
    """
    _, cert, _ = _load_p12(p12, passphrase)
    return SigningCertificate(
        subject=cert.subject.rfc4514_string(),
        issuer=cert.issuer.rfc4514_string(),
        serial_number=format(cert.serial_number, "x"),
        valid_from=_as_date(getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before),
        valid_until=_as_date(getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after),
    )


def sign_cades(
    xml_bytes: bytes,
    p12: bytes | str | os.PathLike,
    passphrase: str | bytes | None = None,
) -> bytes:
    """Sign FatturaPA XML → DER PKCS#7 SignedData with embedded content.

    Produces an *attached* signature (the XML travels inside the envelope,
    as SdI requires for ``.p7m``), SHA-256 digest, signer certificate and any
    CA chain from the P12 included. ``PKCS7Options.Binary`` prevents any
    S/MIME line-ending canonicalization so the XML bytes are embedded verbatim.

    See the module docstring for the ETSI CAdES-BES caveat.

    :param xml_bytes: the FatturaPA XML exactly as it will be transmitted.
    :param p12: PKCS#12 archive as bytes, or a filesystem path to it.
    :param passphrase: P12 passphrase (``None``/empty for unprotected archives).
    :returns: DER-encoded PKCS#7 SignedData bytes (save as ``*.xml.p7m``).
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.serialization import pkcs7
    except ImportError as exc:  # pragma: no cover
        raise SigningUnavailable(
            "la firma CAdES richiede 'cryptography': pip install einvoice[signing]"
        ) from exc

    if not xml_bytes:
        raise ValueError("xml_bytes vuoto: niente da firmare")

    key, cert, extra_certs = _load_p12(p12, passphrase)

    builder = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(xml_bytes)
        .add_signer(cert, key, hashes.SHA256())
    )
    for ca in extra_certs:
        builder = builder.add_certificate(ca)
    return builder.sign(
        serialization.Encoding.DER,
        [pkcs7.PKCS7Options.Binary],  # attached (content embedded), no MIME canonicalization
    )


class P12Signer:
    """:class:`einvoice.transport.Signer`-protocol adapter around :func:`sign_cades`.

    Plug it into :class:`~einvoice.engine.EInvoiceEngine` (``signer=``) to get
    render → sign → transmit in one pass::

        engine = EInvoiceEngine(renderer, transport, signer=P12Signer("cert.p12", "pw"))
    """

    def __init__(self, p12: bytes | str | os.PathLike, passphrase: str | bytes | None = None):
        self._p12 = p12
        self._passphrase = passphrase

    def sign(self, content: bytes, *, filename: str) -> tuple[bytes, str]:
        return sign_cades(content, self._p12, self._passphrase), sign_filename(filename)
