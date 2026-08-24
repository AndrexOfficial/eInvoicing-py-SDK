from einvoice import REGIMI_FISCALI, DocumentType, PaymentMeans, VatExigibility, VatNature


def test_document_type_complete_and_uncl1001_roundtrip():
    codes = {dt.value for dt in DocumentType}
    expected = {f"TD{n:02d}" for n in (1, 2, 3, 4, 5, 6)} | {
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


def test_only_td04_is_credit_note():
    assert DocumentType.CREDIT_NOTE.is_credit_note
    assert not any(dt.is_credit_note for dt in DocumentType if dt.value != "TD04")


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
