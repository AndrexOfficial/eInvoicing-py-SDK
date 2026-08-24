"""Conservation package build: files + manifest hashes + IPdA-like index."""
import hashlib
import json
import zipfile

import pytest

from einvoice import build_conservation_package

XML_A = b"<FatturaElettronica>uno</FatturaElettronica>"
XML_B = b"<FatturaElettronica>due</FatturaElettronica>"


def test_build_package_hashes_and_index(tmp_path):
    src = tmp_path / "b.xml"
    src.write_bytes(XML_B)
    records = [
        {
            "filename": "IT01234567897_00001.xml",
            "content": XML_A,
            "invoice_number": "2026/0001",
            "invoice_date": "2026-01-15",
            "counterpart_vat": "RSSMRA80A01F205X",
        },
        {  # from path, signed variant
            "filename": "IT01234567897_00002.xml.p7m",
            "path": str(src),
            "invoice_number": "2026/0002",
            "invoice_date": "2026-02-10",
            "counterpart_vat": "09876543217",
        },
    ]
    zip_path = build_conservation_package(records, tmp_path / "out", package_name="conservazione_2026")
    assert zip_path.name == "conservazione_2026.zip"

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert {"IT01234567897_00001.xml", "IT01234567897_00002.xml.p7m", "manifest.json", "pdd_index.xml"} == names
        assert zf.read("IT01234567897_00001.xml") == XML_A
        assert zf.read("IT01234567897_00002.xml.p7m") == XML_B

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["algorithm"] == "SHA-256"
        by_name = {d["filename"]: d for d in manifest["documents"]}
        assert by_name["IT01234567897_00001.xml"]["sha256"] == hashlib.sha256(XML_A).hexdigest()
        assert by_name["IT01234567897_00002.xml.p7m"]["sha256"] == hashlib.sha256(XML_B).hexdigest()
        assert by_name["IT01234567897_00001.xml"]["invoice_number"] == "2026/0001"
        assert by_name["IT01234567897_00002.xml.p7m"]["counterpart_vat"] == "09876543217"

        index = zf.read("pdd_index.xml").decode()
        assert "IT01234567897_00001.xml" in index
        assert hashlib.sha256(XML_B).hexdigest() in index
        assert 'documenti="2"' in index


def test_build_package_rejects_empty_and_duplicates(tmp_path):
    with pytest.raises(ValueError):
        build_conservation_package([], tmp_path)
    with pytest.raises(ValueError, match="duplicato"):
        build_conservation_package(
            [{"filename": "a.xml", "content": b"x"}, {"filename": "a.xml", "content": b"y"}],
            tmp_path,
        )
    with pytest.raises(ValueError, match="content"):
        build_conservation_package([{"filename": "a.xml"}], tmp_path)


def test_webhook_provider_requires_url():
    from einvoice import WebhookConservationProvider

    with pytest.raises(ValueError):
        WebhookConservationProvider("")
