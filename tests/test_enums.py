from einvoice import REGIMI_FISCALI, DocumentType, PaymentMeans, VatExigibility, VatNature


def test_document_type_complete_and_uncl1001_roundtrip():
    codes = {dt.value for dt in DocumentType}
    # TD01–TD09 and TD16–TD28. The "semplificata" trio (TD07 fattura, TD08 nota
    # di credito, TD09 nota di debito) was missing, which mattered most for
    # TD08: a credit note the package did not know was one.
    expected = {f"TD{n:02d}" for n in range(1, 10)} | {
        f"TD{n}" for n in range(16, 29)
    }
    assert codes == expected
    for dt in DocumentType:
        assert dt.uncl1001 in {"380", "381", "383", "386"}
    assert DocumentType.INVOICE.uncl1001 == "380"
    assert DocumentType.ADVANCE.uncl1001 == "386"
    assert DocumentType.CREDIT_NOTE.uncl1001 == "381"
    assert DocumentType.DEBIT_NOTE.uncl1001 == "383"
    assert DocumentType.DEFERRED_INVOICE.value == "TD24"
    assert DocumentType.DEFERRED_INVOICE.uncl1001 == "380"
    for td in ("TD16", "TD17", "TD18", "TD19"):
        assert DocumentType(td).uncl1001 == "380"


def test_the_credit_notes_are_td04_and_td08():
    """"Simplified" describes how little the buyer has to be identified, not
    what the document does — TD08 reduces what is owed exactly as TD04 does,
    and UBL puts both on the CreditNote root."""
    credit = {dt.value for dt in DocumentType if dt.is_credit_note}
    assert credit == {"TD04", "TD08"}


def test_the_debit_notes_are_td05_and_td09():
    debit = {dt.value for dt in DocumentType if dt.is_debit_note}
    assert debit == {"TD05", "TD09"}


def test_credit_and_debit_are_mutually_exclusive():
    for dt in DocumentType:
        assert not (dt.is_credit_note and dt.is_debit_note), dt


def test_only_correcting_documents_reference_an_earlier_one():
    correcting = {dt.value for dt in DocumentType if dt.corrects_an_earlier_document}
    assert correcting == {"TD04", "TD05", "TD08", "TD09"}


def test_the_simplified_family_maps_to_the_same_uncl_codes():
    """A simplified document is the same kind of document to a foreign
    receiver, which only sees the UNCL 1001 code."""
    assert DocumentType.SIMPLIFIED_INVOICE.uncl1001 == "380"
    assert DocumentType.SIMPLIFIED_CREDIT_NOTE.uncl1001 == "381"
    assert DocumentType.SIMPLIFIED_DEBIT_NOTE.uncl1001 == "383"


def test_legacy_self_invoice_alias():
    assert DocumentType.SELF_INVOICE is DocumentType.REVERSE_CHARGE_INTERNAL
    assert DocumentType.SELF_INVOICE.value == "TD16"


def test_vat_nature_complete_no_parent_codes():
    codes = {n.value for n in VatNature}
    expected = (
        {"N1", "N2.1", "N2.2", "N4", "N5", "N7"}
        | {f"N3.{i}" for i in range(1, 7)}
        | {f"N6.{i}" for i in range(1, 10)}
    )
    assert codes == expected
    assert not codes & {"N2", "N3", "N6"}   # parent codes rejected by SdI


def test_vat_nature_en16931_category():
    expected = {
        "N1": "O", "N2.1": "O", "N2.2": "O",
        "N3.1": "G", "N3.2": "K", "N3.3": "E", "N3.4": "E", "N3.5": "E", "N3.6": "E",
        "N4": "E", "N5": "E", "N7": "O",
    } | {f"N6.{i}": "AE" for i in range(1, 10)}
    assert {n.value: n.en16931_category for n in VatNature} == expected


def test_vat_nature_default_exemption_reason():
    for n in VatNature:
        assert n.default_exemption_reason
    assert "art. 8" in VatNature.NOT_TAXABLE_EXPORT.default_exemption_reason


def test_payment_means_complete_and_uncl4461_roundtrip():
    codes = {pm.value for pm in PaymentMeans}
    assert codes == {f"MP{n:02d}" for n in range(1, 24)}
    for pm in PaymentMeans:
        assert pm.uncl4461.isdigit()
    assert PaymentMeans.CASH.uncl4461 == "10"
    assert PaymentMeans.BANK_TRANSFER.uncl4461 == "30"
    assert PaymentMeans.CARD.uncl4461 == "48"
    assert PaymentMeans.RIBA.uncl4461 == "49"
    assert PaymentMeans.SEPA_DD_CORE.uncl4461 == "59"
    assert PaymentMeans.PAGOPA.uncl4461 == "68"
    assert PaymentMeans.MAV.uncl4461 == "97"


def test_vat_exigibility_values():
    assert {e.value for e in VatExigibility} == {"I", "D", "S"}


def test_regimi_fiscali():
    assert "RF01" in REGIMI_FISCALI
    assert "RF19" in REGIMI_FISCALI
    assert "RF20" in REGIMI_FISCALI
    assert "RF03" not in REGIMI_FISCALI   # ritirato
    assert "RF99" not in REGIMI_FISCALI
