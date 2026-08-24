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
| `ubl` / `peppol` | `UblRenderer` | UBL 2.1 **Peppol BIS Billing 3.0** (EN 16931). Europa / PA / cross-border. |

`build_fattura_xml(invoice)` e `build_ubl_xml(invoice)` sono le funzioni dirette
(ritornano `bytes`) se non ti serve l'oggetto `RenderedDocument`.

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

## Profili paese (`einvoice.countries`) — UE-27 + UK + US

Il modulo `countries` collega paese del venditore → formato/regole:

- `profile_for("DE")` → `CountryProfile` con `default_standard` ("fatturapa"
  per IT, "ubl" altrove), `tax_scheme` ("VAT" UE/UK, **"STT"** US — UN/ECE 5153
  sales tax), `tax_id_pattern` strutturale (P.IVA VIES, VAT GB, EIN US),
  `currency_hint` e note operative.
- `validate_tax_id("NL", "NL123456789B01")` — check strutturale del tax-id
  (prefisso paese/EL tollerato, spazi ignorati). Nessun checksum/VIES lookup.
- `renderer_for_country("DE", xrechnung=True)` — il renderer giusto per il
  paese: FatturaPA per IT, UBL Peppol BIS per il resto; `xrechnung=True` usa il
  CIUS XRechnung 3.0 (costante `XRECHNUNG_CUSTOMIZATION`); per US imposta
  `tax_scheme="STT"` automaticamente.
- `Invoice.validate()` delega al profilo del paese del **venditore**: le regole
  italiane (RegimeFiscale, CodiceDestinatario FPA12/FPR12, CAP, Natura ↔
  aliquota) valgono solo per venditori IT; il profilo US **rifiuta** le Nature
  IVA; ogni profilo verifica la struttura del tax-id del venditore.
- `PEPPOL_EAS_BY_COUNTRY` copre tutta l'UE + GB (9932); la Grecia usa il
  prefisso VIES `EL` sia nel `CompanyID` che nell'`EndpointID` (EAS 9933).

`UblRenderer(tax_scheme=...)` propaga lo schema a `PartyTaxScheme`,
`TaxCategory`/`ClassifiedTaxCategory` e `AllowanceCharge`; per gli USA il
`CompanyID` è l'EIN senza prefisso.

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

Per **CII** (UN/CEFACT, base di Factur-X/ZUGFeRD) si scrive un renderer analogo
sulla sintassi `CrossIndustryInvoice`; **Factur-X/ZUGFeRD** aggiungono poi un
passo di embedding del CII XML in un PDF/A-3 (estensione lato rendering/PDF).
