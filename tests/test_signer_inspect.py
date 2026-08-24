"""Reading a P12 without signing with it.

Both hosting platforms (TableOS, GymOS) had reached into ``signer._load_p12``
— a private helper — to answer "are these signing credentials usable?" when an
operator saves them. That is a real question with no public answer, so these
tests cover the public one, plus the question nobody was asking: a certificate
has an expiry date, and a signature made with an expired one is refused
downstream while the stored configuration still looks perfectly valid.
"""
from datetime import UTC, date, datetime, timedelta

import pytest

from einvoice import SigningCertificate, SigningUnavailable, inspect_p12
from einvoice.errors import EInvoiceError

cryptography = pytest.importorskip("cryptography")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


def make_p12(*, passphrase: bytes | None = b"segreto", not_before=None, not_after=None,
             common_name="Studio Rossi"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IT"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(0x2A)
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    enc = (serialization.BestAvailableEncryption(passphrase) if passphrase
           else serialization.NoEncryption())
    return pkcs12.serialize_key_and_certificates(b"cert", key, cert, None, enc)


def test_it_reports_who_the_certificate_belongs_to():
    cert = inspect_p12(make_p12(), "segreto")

    assert isinstance(cert, SigningCertificate)
    assert "Studio Rossi" in cert.subject
    assert "IT" in cert.issuer
    assert cert.serial_number == "2a"


def test_the_wrong_passphrase_is_a_value_error_not_a_silent_pass():
    """The failure both platforms were catching with a bare ``except``."""
    with pytest.raises(ValueError, match="passphrase"):
        inspect_p12(make_p12(), "sbagliata")


def test_bytes_that_are_not_a_p12_at_all():
    with pytest.raises(ValueError):
        inspect_p12(b"questo non e un archivio PKCS#12", "segreto")


def test_an_unprotected_archive_needs_no_passphrase():
    cert = inspect_p12(make_p12(passphrase=None))
    assert cert.valid_until > cert.valid_from


def test_an_empty_string_passphrase_means_no_passphrase():
    """Web forms submit "" for an untouched field; it must not mean b""."""
    assert inspect_p12(make_p12(passphrase=None), "") is not None


def test_it_reads_validity_as_dates():
    now = datetime.now(UTC)
    cert = inspect_p12(
        make_p12(not_before=now - timedelta(days=10), not_after=now + timedelta(days=40)),
        "segreto")

    assert cert.valid_from == (now - timedelta(days=10)).date()
    assert cert.valid_until == (now + timedelta(days=40)).date()


def test_expiry_questions_are_answered_against_a_given_day():
    cert = SigningCertificate(
        subject="CN=x", issuer="CN=y", serial_number="1",
        valid_from=date(2026, 1, 1), valid_until=date(2026, 6, 30))

    assert cert.days_until_expiry(on=date(2026, 6, 1)) == 29
    assert cert.expires_within(30, on=date(2026, 6, 1))
    assert not cert.expires_within(30, on=date(2026, 5, 1))
    assert not cert.is_expired(on=date(2026, 6, 30))     # valid through its last day
    assert cert.is_expired(on=date(2026, 7, 1))
    assert cert.days_until_expiry(on=date(2026, 7, 10)) == -10
    assert cert.is_not_yet_valid(on=date(2025, 12, 31))


def test_an_expired_certificate_still_opens_and_says_so():
    """Refusing to read it would leave an operator unable to see WHY."""
    now = datetime.now(UTC)
    cert = inspect_p12(
        make_p12(not_before=now - timedelta(days=800), not_after=now - timedelta(days=5)),
        "segreto")

    assert cert.is_expired()
    assert cert.days_until_expiry() == -5
    assert cert.expires_within(30)


def test_the_missing_extra_has_its_own_error_type():
    """A platform must be able to tell "cannot check here" from "this is bad".

    Catching them together is how a corrupt archive gets stored as valid.
    """
    assert issubclass(SigningUnavailable, EInvoiceError)
    assert issubclass(SigningUnavailable, RuntimeError)   # what callers caught before
    assert not issubclass(SigningUnavailable, ValueError)  # never confusable with bad input


def test_it_accepts_a_path_as_well_as_bytes(tmp_path):
    archive = tmp_path / "firma.p12"
    archive.write_bytes(make_p12())

    assert inspect_p12(archive, "segreto").serial_number == "2a"
