"""``python -m einvoice`` — the shell surface of the engine."""
import json
import pathlib

import pytest

from einvoice.cli import EXIT_INVALID, EXIT_OK, EXIT_USAGE, main

MINIMAL = {
    "number": "2026/0001",
    "date": "2026-06-05",
    "seller": {
        "name": "Trattoria da Mario", "vat_number": "07643520567",
        "address": {"street": "Via Roma 1", "postcode": "20100", "city": "Milano", "province": "MI"},
    },
    "buyer": {
        "name": "ACME Srl", "vat_number": "09876543217", "sdi_code": "ABCDEFG",
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
        "name": "Muster GmbH", "vat_number": "136695976", "country_code": "DE",
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
    assert main(["countries", "IT", "--tax-id", "01234567897"]) == EXIT_OK
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


# ── the country / platform / advisory surface ──────────────────────────────


def test_check_reports_advisories_without_failing(tmp_path, capsys):
    """Warnings must not break a pipeline by default."""
    cross_border = {**MINIMAL,
                    "seller": {**MINIMAL["seller"], "vat_number": "07643520567"},
                    "buyer": {"name": "Muster GmbH", "vat_number": "136695976",
                              "country_code": "DE",
                              "address": {"street": "Hauptstr 1", "postcode": "10115",
                                          "city": "Berlin", "country": "DE"}}}
    path = tmp_path / "x.json"
    path.write_text(json.dumps(cross_border), encoding="utf-8")

    assert main(["check", str(path)]) == EXIT_OK
    assert "intra_eu_vat" in capsys.readouterr().out


def test_check_strict_turns_advisories_into_a_failure(tmp_path):
    cross_border = {**MINIMAL,
                    "seller": {**MINIMAL["seller"], "vat_number": "07643520567"},
                    "buyer": {"name": "Muster GmbH", "vat_number": "136695976",
                              "country_code": "DE",
                              "address": {"street": "Hauptstr 1", "postcode": "10115",
                                          "city": "Berlin", "country": "DE"}}}
    path = tmp_path / "x.json"
    path.write_text(json.dumps(cross_border), encoding="utf-8")

    assert main(["check", str(path), "--strict"]) == EXIT_INVALID


def test_check_on_a_clean_invoice_says_so(invoice_file, capsys):
    assert main(["check", invoice_file]) == EXIT_OK
    assert "nessun rilievo" in capsys.readouterr().out


def test_countries_listing_shows_the_regulatory_date(capsys):
    """Policy data goes stale; the reader must see how old it is."""
    assert main(["countries"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "CH" in out and "verificati al" in out


def test_country_detail_includes_the_einvoicing_regime(capsys):
    assert main(["countries", "CH"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["currency"] == "CHF"
    assert data["einvoicing"]["network"] == "peppol"
    assert data["tax_id_validation"] == "checksum"


def test_tax_id_check_reports_the_validation_strength(capsys):
    assert main(["countries", "CH", "--tax-id", "CHE-116.281.710"]) == EXIT_OK
    assert "checksum" in capsys.readouterr().out


def test_providers_lists_platforms(capsys):
    assert main(["providers"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "fiscozen" in out and "storecove" in out


def test_providers_filters_by_country(capsys):
    assert main(["providers", "--country", "IT"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "fiscozen" in out and "chorus_pro" not in out


def test_providers_lists_the_categories(capsys):
    assert main(["providers", "--kinds"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "national_portal" in out and "sdi_intermediary" in out


def test_providers_filters_by_kind(capsys):
    assert main(["providers", "--kind", "national_portal"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "chorus_pro" in out and "fiscozen" not in out


def test_providers_table_never_shears_on_a_long_key(capsys):
    """Column widths come from the data; a fixed width used to break the row
    for `swisscom_conextrade`."""
    assert main(["providers"]) == EXIT_OK
    rows = [r for r in capsys.readouterr().out.splitlines()
            if r and not r.startswith(("KEY", " ")) and "piattaforme" not in r]
    kind_column = [r.index("access_point") if "access_point" in r else None for r in rows]
    starts = {c for c in kind_column if c is not None}
    assert len(starts) == 1, f"category column is not aligned: {sorted(starts)}"


def test_provider_detail_states_whether_endpoints_are_verified(capsys):
    assert main(["providers", "fiscozen"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["endpoints_verified"] is False
    assert data["renderer"] == "fatturapa"


def test_render_cii_for_a_french_seller(tmp_path):
    french = {**MINIMAL, "seller": {
        "name": "Société Exemple", "vat_number": "40303265045", "country_code": "FR",
        "address": {"street": "1 rue de Rivoli", "postcode": "75001",
                    "city": "Paris", "country": "FR"}}}
    path = tmp_path / "fr.json"
    path.write_text(json.dumps(french), encoding="utf-8")
    out = tmp_path / "fr.xml"

    assert main(["render", str(path), "--standard", "cii", "-o", str(out)]) == EXIT_OK

    xml = out.read_bytes()
    assert b"CrossIndustryInvoice" in xml
    assert b"urn:cen.eu:en16931:2017" in xml


# ── the inbound half ───────────────────────────────────────────────────────


@pytest.fixture
def received(tmp_path, invoice_file):
    """An XML document as a supplier would have sent it."""
    out = tmp_path / "received.xml"
    assert main(["render", invoice_file, "--standard", "cii", "-o", str(out)]) == EXIT_OK
    return str(out)


def test_parse_turns_a_received_document_back_into_json(received, capsys):
    assert main(["parse", received]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["number"] == "2026/0001"
    assert data["seller"]["vat_number"] == "07643520567"


def test_parse_output_is_valid_input(received, tmp_path):
    """Receive, store, forward — the shape of any AP workflow."""
    back = tmp_path / "back.json"
    assert main(["parse", received, "-o", str(back)]) == EXIT_OK
    assert main(["validate", str(back)]) == EXIT_OK
    assert main(["render", str(back), "--standard", "ubl", "-o",
                 str(tmp_path / "again.xml")]) == EXIT_OK


def test_parse_can_be_told_the_format(received, capsys):
    assert main(["parse", received, "--standard", "cii"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["number"] == "2026/0001"


def test_inspect_summarises_who_and_how_much(received, capsys):
    assert main(["inspect", received]) == EXIT_OK
    out = capsys.readouterr().out
    assert "formato      cii" in out
    assert "Trattoria da Mario" in out
    assert "122.00" in out


def test_inspect_fails_when_the_stated_total_contradicts_the_lines(received, tmp_path, capsys):
    """The one discrepancy worth stopping a pipeline for."""
    tampered = tmp_path / "tampered.xml"
    text = pathlib.Path(received).read_text(encoding="utf-8")
    swapped = text.replace("<ram:GrandTotalAmount>122.00",
                           "<ram:GrandTotalAmount>9999.00")
    assert swapped != text, "fixture no longer matches the rendered total"
    tampered.write_text(swapped, encoding="utf-8")

    assert main(["inspect", str(tampered)]) == EXIT_INVALID
    assert "DISALLINEAMENTO" in capsys.readouterr().out


def test_inspect_reports_advisories_too(tmp_path, capsys):
    """A cross-border supply with domestic VAT is worth seeing on arrival."""
    cross = {**MINIMAL,
             "seller": {**MINIMAL["seller"], "vat_number": "07643520567"},
             "buyer": {"name": "Muster GmbH", "vat_number": "136695976",
                       "country_code": "DE",
                       "address": {"street": "Hauptstr 1", "postcode": "10115",
                                   "city": "Berlin", "country": "DE"}}}
    src = tmp_path / "x.json"
    src.write_text(json.dumps(cross), encoding="utf-8")
    xml = tmp_path / "x.xml"
    main(["render", str(src), "--standard", "ubl", "-o", str(xml)])

    assert main(["inspect", str(xml)]) == EXIT_OK
    assert "intra_eu_vat" in capsys.readouterr().out


def test_parsing_a_document_we_do_not_understand_fails_cleanly(tmp_path, capsys):
    junk = tmp_path / "junk.xml"
    junk.write_text("<?xml version='1.0'?><purchaseOrder/>", encoding="utf-8")

    assert main(["parse", str(junk)]) == EXIT_INVALID
    err = capsys.readouterr().err
    assert "errore:" in err and "Traceback" not in err
