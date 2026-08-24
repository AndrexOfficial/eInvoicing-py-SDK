# Renderers (formati / country adapters)

Un renderer trasforma il modello neutro `Invoice` nei byte di uno standard.

```python
from einvoice.formats import get_renderer, available_renderers
available_renderers()                  # ['fatturapa', 'peppol', 'ubl']
doc = get_renderer("fatturapa").render(invoice)   # RenderedDocument
doc.standard, doc.mime, doc.filename, doc.content  # 'fatturapa', 'application/xml', 'IT..._00001.xml', b'<?xml...'
```

Interfaccia:

```python
class InvoiceRenderer(ABC):
    standard: str
    def render(self, invoice: Invoice) -> RenderedDocument: ...
```

## Formati inclusi

| Standard | Classe | Uso |
|---|---|---|
| `fatturapa` | `FatturaPARenderer` | Italia / SdI (FatturaPA 1.2). Vedi [FATTURAPA.md](FATTURAPA.md). |
| `ubl` / `peppol` | `UblRenderer` | UBL 2.1 **Peppol BIS Billing 3.0** (EN 16931) + CIUS nazionali. |
| `cii` / `facturx` / `zugferd` | `CiiRenderer` | UN/CEFACT **Cross Industry Invoice** (EN 16931): Factur-X, ZUGFeRD, Chorus Pro. |

`build_fattura_xml(invoice)`, `build_ubl_xml(invoice)` e `build_cii_xml(invoice)`
sono le funzioni dirette (ritornano `bytes`) se non ti serve l'oggetto
`RenderedDocument`.

### Note di credito: radici diverse, non solo codici diversi

UBL 2.1 ha uno **schema separato** per le note di credito: radice `CreditNote`,
`cac:CreditNoteLine`, `cbc:CreditedQuantity`, e **niente** `cbc:DueDate` a
livello documento. Emettere una radice `Invoice` con `InvoiceTypeCode` 381
produce un documento che nessun destinatario Peppol accetta.

CII invece ha una radice sola e cambia solo il `TypeCode`. FatturaPA usa
`TipoDocumento`. In tutti e tre i casi la scelta la fa
`DocumentType.is_credit_note` — che copre `TD04` **e** `TD08`. Dettagli in
[CORRECTIONS.md](CORRECTIONS.md).

### Perché due sintassi EN 16931

EN 16931 è un modello **semantico**, e ammette due sintassi: UBL e CII. Portano
lo stesso significato ma non sono intercambiabili sul filo — un destinatario ne
accetta una sola. La Francia e ZUGFeRD scambiano CII; il grosso di Peppol
scambia UBL. Coprire solo UBL avrebbe lasciato fuori Chorus Pro e ZUGFeRD.

I due renderer producono **gli stessi totali**: è una proprietà verificata su
tutti e 30 i paesi in `tests/test_all_countries.py`, e una divergenza fra loro
è sempre un bug.

## UBL / EN 16931 (Peppol BIS 3.0)

`UblRenderer` emette un documento UBL 2.1 con `CustomizationID` Peppol BIS
3.0. È la base EN 16931 da cui derivano i CIUS nazionali.

- **Nota di credito**: se `document_type.is_credit_note` la root è
  `CreditNote-2` con `cbc:CreditNoteTypeCode` (381) e righe
  `cac:CreditNoteLine`/`cbc:CreditedQuantity`; altrimenti `Invoice-2`.
- **BuyerReference** (BT-10, PEPPOL-EN16931-R003): mai assente —
  `Invoice.buyer_reference`, altrimenti `cac:OrderReference` da una reference
  `kind=="order"`, altrimenti fallback al numero fattura.
- **EndpointID**: da `Party.peppol_endpoint()` — endpoint espliciti
  (`endpoint_scheme`/`endpoint_id`) oppure derivati dalla P.IVA col mapping
  EAS per paese (`PEPPOL_EAS_BY_COUNTRY`: IT → `0211`, DE → `9930`,
  FR → `9957`, NL → `9944`, BE → `9925`, ES → `9920`, AT → `9914`,
  SE → `0007`, NO → `0192`, DK → `0184`, FI → `0216`); per paesi non mappati
  l'elemento è omesso.
- **Categorie IVA** (UNCL 5305, da `VatNature.en16931_category`):

  | Natura | Categoria EN 16931 |
  |---|---|
  | aliquota > 0 | `S` |
  | `N3.1` (esportazioni) | `G` |
  | `N3.2` (cessioni intra-UE) | `K` |
  | `N6.*` (reverse charge) | `AE` |
  | `N4` (esenti) | `E` |
  | `N3.3`–`N3.6`, `N5` | `E` (assimilate a esenzione lato EN) |
  | `N1`, `N2.*`, `N7` | `O` (fuori campo; senza `cbc:Percent`) |

  Per le categorie ≠ `S` il `TaxSubtotal/cac:TaxCategory` porta
  `cbc:TaxExemptionReason` (da `LineItem.exemption_reason` o dal default della
  natura).
- **Quadratura (BR-CO-10/13/15)**: `LineExtensionAmount = Σ totali riga`
  (`lines_total()`), `AllowanceTotalAmount`/`ChargeTotalAmount` dagli
  allowance/charge di documento; il **bollo** è reso come charge con categoria
  `O` (con un proprio TaxSubtotal a imposta zero) e la **cassa previdenziale**
  come charge nella sua categoria, così
  `TaxExclusive = lines − allowances + charges` e
  `TaxInclusive = TaxExclusive + IVA` tornano sempre.
  `PayableRoundingAmount` ← `Invoice.rounding`;
  `PayableAmount = TaxInclusive + rounding` (le ritenute non riducono il
  payable: EN 16931 non le modella).
- **Pagamenti**: `cbc:PaymentID` (numero fattura come remittance info),
  `cac:PaymentTerms/cbc:Note` ← `payment_terms_note`.
- **Righe**: `cac:AllowanceCharge` di riga da `LineItem.discounts`;
  `InvoicedQuantity/@unitCode` passa `unit_of_measure` così com'è (default
  `C62`) — per output Peppol valido deve essere un codice UNECE Rec. 20.

## CII / Factur-X / ZUGFeRD

`CiiRenderer` emette `rsm:CrossIndustryInvoice` (D16B). Il **profilo** dichiara
quale insieme di regole il documento segue:

```python
get_renderer("cii")                          # en16931 ("COMFORT") — default
get_renderer("cii", profile="extended")
get_renderer("cii", profile="xrechnung")     # XRechnung su sintassi CII
get_renderer("cii", guideline="urn:…")       # identificativo esplicito
```

Profili in `FACTURX_PROFILES`: `minimum`, `basicwl`, `basic`, `en16931`,
`extended`, `xrechnung`.

Due cose su cui è facile sbagliare, e che qui sono gestite:

- **L'ordine degli elementi è vincolante.** Lo schema CII è una sequenza:
  emettere `ram:Name` prima di `ram:ID` produce un documento semanticamente
  giusto e **non valido**. È il motivo per cui il modulo è scritto in linea
  retta invece che con helper che "aggiungono un campo dove capita".
- **Le date sono incapsulate**: `<ram:IssueDateTime><udt:DateTimeString
  format="102">20260824</udt:DateTimeString></ram:IssueDateTime>`, mai una
  stringa ISO nuda. Idem il booleano di `ram:ChargeIndicator`, che vive in un
  `udt:Indicator` annidato.

**Fuori perimetro**: qui si genera l'XML. *Factur-X* propriamente detto è
quell'XML incorporato in un **PDF/A-3**; l'incapsulamento richiede un toolkit
PDF ed è un confine deliberato.

## Profili paese (`einvoice.countries`) — UE-27 + UK + CH + US

Il modulo `countries` collega paese del venditore → formato, regole e obblighi.
La matrice completa è in [COUNTRIES.md](COUNTRIES.md).

- `profile_for("CH")` → `CountryProfile` con `default_standard`, `tax_scheme`
  ("VAT" UE/UK/CH, **"STT"** US), `vat_rates` note, `currency_hint`,
  `tax_id_validation` (`"checksum"` o `"structural"`) e `regime`
  (:class:`EInvoicingRegime`: rete, obbligo B2G/B2B, CIUS, formato nazionale).
- `validate_tax_id("DE", "DE 136 695 976")` — **cifra di controllo verificata**
  per 20 paesi, strutturale per gli altri, con le forme stampate normalizzate.
- `renderer_for_country(code, b2g=True)` — il renderer giusto **e il CIUS
  giusto**: XRechnung (DE), NLCIUS (NL), CIUS-RO (RO). Mandare Peppol BIS liscio
  a chi si aspetta un CIUS è uno scarto, non un avviso. `standard="cii"` forza
  la sintassi CII; per gli US imposta `tax_scheme="STT"` da sé.
- `Invoice.validate()` delega al profilo del **venditore**: le regole italiane
  valgono solo per venditori IT; i profili US e CH **rifiutano** le Nature IVA
  italiane; ogni profilo valida il tax-id del venditore.
- `Invoice.check()` restituisce rilievi **non bloccanti** (aliquota implausibile,
  cessione intra-UE con IVA, esportazione tassata, scadenza anteriore…).
- `PEPPOL_EAS_BY_COUNTRY` copre UE + GB (9932) + **CH (0183)**. La Grecia usa il
  prefisso VIES `EL`; la Svizzera **non** viene prefissata, perché l'UID porta
  già il suo `CHE`.

`UblRenderer(tax_scheme=...)` e `CiiRenderer(tax_scheme=...)` propagano lo
schema d'imposta a tutti i blocchi fiscali.

## Aggiungere un formato (es. XRechnung / CII)

```python
from einvoice.formats import InvoiceRenderer, RenderedDocument, register_renderer
from einvoice.formats.ubl import build_ubl_xml

class XRechnungRenderer(InvoiceRenderer):
    standard = "xrechnung"
    _CIUS = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
    def render(self, invoice):
        xml = build_ubl_xml(invoice, customization=self._CIUS)
        return RenderedDocument("xrechnung", xml, "application/xml", f"{invoice.number}-xrechnung.xml")

register_renderer("xrechnung", XRechnungRenderer)
```

**CII è ora incluso** (`einvoice.formats.cii`) — l'esempio sopra resta valido
per un CIUS su UBL. Per Factur-X/ZUGFeRD completi manca solo l'embedding
dell'XML in un PDF/A-3, che richiede un toolkit PDF.
