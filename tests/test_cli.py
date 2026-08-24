"""``python -m einvoice`` — the shell surface of the engine."""
import json

import pytest

from einvoice.cli import EXIT_INVALID, EXIT_OK, EXIT_USAGE, main

MINIMAL = {
    "number": "2026/0001",
    "date": "2026-06-05",
    "seller": {
        "name": "Trattoria da Mario", "vat_number": "01234567890",
        "address": {"street": "Via Roma 1", "postcode": "20100", "city": "Milano", "province": "MI"},
    },
    "buyer": {
        "name": "ACME Srl", "vat_number": "09876543210", "sdi_code": "ABCDEFG",
        "address": {"street": "Via Verdi 9", "postcode": "00100", "city": "Roma", "province": "RM"},
    },
    "lines": [{"description": "Cena", "quantity": "1", "unit_price": "100.00", "vat_rate": "22"}],
}


@pytest.fixture
def invoice_file(tmp_path):
    path = tmp_path / "fattura.json"
    path.write_text(json.dumps(MINIMAL), encoding="utf-8")
    return str(path)


def test_validate_accepts_a_good_invoice(invoice_file, capsys):
    assert main(["validate", invoice_file]) == EXIT_OK
    assert "122.00" in capsys.readouterr().out


def test_validate_rejects_a_bad_invoice_without_a_traceback(tmp_path, capsys):
    """A rejected invoice is the tool working — it must read as a finding."""
    broken = tmp_path / "bad.json"
    broken.write_text(json.dumps({**MINIMAL, "lines": []}), encoding="utf-8")

    assert main(["validate", str(broken)]) == EXIT_INVALID
    err = capsys.readouterr().err
    assert "errore:" in err and "Traceback" not in err


def test_usage_error_is_a_different_exit_code_than_a_bad_invoice(invoice_file):
    """CI needs to tell "the invoice is wrong" from "the command is wrong"."""
    with pytest.raises(SystemExit) as exc:
        main(["render", invoice_file, "--standard", "klingon"])
    assert exc.value.code == EXIT_USAGE


def test_missing_file_is_reported_by_name(capsys):
    assert main(["validate", "/nope/missing.json"]) == EXIT_INVALID
    assert "missing.json" in capsys.readouterr().err


def test_render_writes_fatturapa_xml(invoice_file, tmp_path):
    out = tmp_path / "out.xml"

    assert main(["render", invoice_file, "-o", str(out)]) == EXIT_OK

    xml = out.read_bytes()
    assert xml.startswith(b"<?xml")
    assert b"FatturaElettronica" in xml


def test_render_to_stdout_emits_bytes_not_re_encoded_text(invoice_file, capsysbinary):
    assert main(["render", invoice_file]) == EXIT_OK
    assert capsysbinary.readouterr().out.startswith(b"<?xml")


def test_render_by_country_picks_ubl_outside_italy(tmp_path):
    """A German seller must not get a FatturaPA."""
    german = {**MINIMAL, "seller": {
        "name": "Muster GmbH", "vat_number": "123456789", "country_code": "DE",
        "address": {"street": "Hauptstr 1", "postcode": "10115", "city": "Berlin", "country": "DE"},
    }}
    path = tmp_path / "de.json"
    path.write_text(json.dumps(german), encoding="utf-8")
    out = tmp_path / "de.xml"

    assert main(["render", str(path), "--country", "DE", "-o", str(out)]) == EXIT_OK

    assert b"Invoice" in out.read_bytes()
    assert b"FatturaElettronica" not in out.read_bytes()


def test_totals_prints_the_vat_breakdown(invoice_file, capsys):
    assert main(["totals", invoice_file]) == EXIT_OK

    data = json.loads(capsys.readouterr().out)
    assert data["imponibile_totale"] == "100.00"
    assert data["imposta_totale"] == "22.00"
    assert data["riepiloghi"][0]["aliquota"] == "22.00"


def test_normalize_output_is_valid_input(invoice_file, tmp_path, capsys):
    assert main(["normalize", invoice_file]) == EXIT_OK
    canonical = tmp_path / "canonical.json"
    canonical.write_text(capsys.readouterr().out, encoding="utf-8")

    assert main(["validate", str(canonical)]) == EXIT_OK


def test_countries_lists_profiles(capsys):
    assert main(["countries"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "IT" in out and "DE" in out and "US" in out


def test_country_detail_reports_the_default_standard(capsys):
    assert main(["countries", "IT"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["default_standard"] == "fatturapa"


def test_tax_id_check_exits_nonzero_when_invalid(capsys):
    assert main(["countries", "IT", "--tax-id", "01234567890"]) == EXIT_OK
    assert main(["countries", "IT", "--tax-id", "nope"]) == EXIT_INVALID


def test_transports_and_renderers_list_what_is_wired(capsys):
    assert main(["transports"]) == EXIT_OK
    transports = capsys.readouterr().out
    assert "aruba" in transports and "peppol" in transports

    assert main(["renderers"]) == EXIT_OK
    assert "fatturapa" in capsys.readouterr().out


def test_sign_without_cryptography_or_a_bad_p12_fails_cleanly(invoice_file, tmp_path, capsys):
    """Either outcome is a clean message, never a traceback."""
    xml = tmp_path / "doc.xml"
    main(["render", invoice_file, "-o", str(xml)])
    junk = tmp_path / "not-a-cert.p12"
    junk.write_bytes(b"definitely not a PKCS#12")

    assert main(["sign", str(xml), "--p12", str(junk)]) == EXIT_INVALID
    assert "Traceback" not in capsys.readouterr().err
