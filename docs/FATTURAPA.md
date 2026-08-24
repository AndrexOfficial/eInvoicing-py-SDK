# FatturaPA — mappatura e riferimenti

Riferimento: schema **FatturaElettronica v1.2** dell'Agenzia delle Entrate.
Namespace: `http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2`.

## Dominio → XML

| Dominio (`models.py`) | Elemento FatturaPA |
|---|---|
| `Invoice.transmission_format` | root `versione` + `FormatoTrasmissione` (`FPR12`/`FPA12`) |
| `Invoice.resolved_recipient()` | `CodiceDestinatario` (7 char) + opz. `PECDestinatario` |
| `Invoice.document_type` | `DatiGeneraliDocumento/TipoDocumento` (`TD01`, `TD04`…) |
| `Invoice.currency` / `date` / `number` | `Divisa` / `Data` / `Numero` |
| `Invoice.total_document()` | `ImportoTotaleDocumento` |
| `Invoice.causale` | `Causale` |
| `Party` (seller) | `CedentePrestatore` (`IdFiscaleIVA`, `CodiceFiscale`, `Anagrafica`, `RegimeFiscale`, `Sede`) |
| `Party` (buyer) | `CessionarioCommittente` (`IdFiscaleIVA?`, `CodiceFiscale?`, `Anagrafica`, `Sede`) |
| `LineItem` | `DettaglioLinee` (`NumeroLinea`, `Descrizione`, `Quantita`, `UnitaMisura?`, `PrezzoUnitario`, `PrezzoTotale`, `AliquotaIVA`) |
| `Invoice.vat_summary()` | `DatiRiepilogo` per (aliquota, natura) (`ImponibileImporto`, `Imposta`, `EsigibilitaIVA`, `RiferimentoNormativo?`) |
| `Payment` | `DatiPagamento/DettaglioPagamento` (`ModalitaPagamento`, `DataScadenzaPagamento?`, `ImportoPagamento`, `IBAN?`) |

## Scorporo IVA (prezzi lordi → netti)

FatturaPA lavora su importi **netti** (imponibile) e aggiunge l'IVA. I POS
salvano spesso prezzi **IVA inclusa**. `LineItem.from_gross(...)` fa lo scorporo:

```
netto_unitario = lordo / (1 + aliquota/100)
```

I `DatiRiepilogo` sono calcolati raggruppando le righe per aliquota:
`imponibile = Σ PrezzoTotale`, `imposta = imponibile × aliquota/100`.
`ImportoTotaleDocumento = Σ (imponibile + imposta)`.

## Naming del file SDI

`{IdPaese}{IdCodice}_{progressivo}.xml`, es. `IT01234567890_00007.xml`.
Il `progressivo` è alfanumerico `[A-Z0-9]` (max 5), **univoco** per
trasmittente. `naming.to_base36(n)` codifica un contatore intero; la piattaforma
persiste solo l'`int`.

## Codici (liste complete 1.2.2)

- **TipoDocumento** (`DocumentType`): TD01–TD06 + TD16–TD28 completi.
  Per la ristorazione è fondamentale `TD24` (**fattura differita** art. 21
  c.4 lett. a, `DocumentType.DEFERRED_INVOICE`). TD16–TD19 sono le
  integrazioni/autofatture estero e reverse charge, TD20–TD23 e TD26–TD28 le
  altre autofatture/casi speciali.
- **RegimeFiscale** (cedente): validato contro `REGIMI_FISCALI`
  (RF01, RF02, RF04–RF19 + RF20 franchigia transfrontaliera; RF03 ritirato).
- **ModalitaPagamento** (`PaymentMeans`): MP01–MP23 completi, ciascuno con il
  mapping `.uncl4461` verso EN 16931 (fallback generico `97`).
- **CondizioniPagamento**: `TP01` a rate, `TP02` completo, `TP03` anticipo.
- **Natura** (`VatNature`, quando `AliquotaIVA = 0`): lista completa post-2021
  con i soli sotto-codici puntati — `N1`, `N2.1`/`N2.2`, `N3.1`–`N3.6`, `N4`,
  `N5`, `N6.1`–`N6.9`, `N7` (i padri N2/N3/N6 non sono più ammessi da SdI).
  Si imposta sulla riga (`LineItem(..., nature=VatNature.EXEMPT)`);
  `validate()` la richiede per le righe a 0% e la vieta con aliquota > 0
  (mutuamente esclusive). Ogni natura ha `.en16931_category` (mapping UBL,
  vedi [RENDERERS.md](RENDERERS.md)) e `.default_exemption_reason` (testo
  usato come `RiferimentoNormativo`/`TaxExemptionReason` di default).
- **EsigibilitaIVA** (`VatExigibility`): `I` immediata (default), `D`
  differita, `S` split payment. Override con `Invoice.exigibility`; se assente
  vale la logica `split_payment → S, altrimenti I`.

## Blocchi opzionali supportati

Oltre al backbone, `FatturaPARenderer` emette (quando valorizzati sul modello,
sempre nell'ordine della sequence XSD):

- **DatiRitenuta** ← `Invoice.withholdings` (`WithholdingTax`)
- **DatiBollo** ← `Invoice.stamp_duty`
- **DatiCassaPrevidenziale** ← `Invoice.funds` (`SocialSecurityFund`: TipoCassa,
  AlCassa, ImportoContributoCassa, ImponibileCassa?, AliquotaIVA, Ritenuta SI?,
  Natura?). Il contributo **concorre all'imponibile IVA** della sua aliquota
  nei `DatiRiepilogo` (via `vat_summary()`).
- **ScontoMaggiorazione** (documento) ← `Invoice.allowances_charges`
- **Arrotondamento** ← `Invoice.rounding` (incluso in `ImportoTotaleDocumento`)
- **Art73 = "SI"** ← `Invoice.art73`
- **CodiceArticolo** ← `LineItem.article_code` (+ `article_code_type`, default `INTERNO`)
- **DataInizioPeriodo / DataFinePeriodo** ← `LineItem.period_start` / `period_end`
- **ScontoMaggiorazione di linea** ← `LineItem.discounts` (`PrezzoTotale` è già
  al netto degli sconti riga)
- **RiferimentoNormativo** nei `DatiRiepilogo` con Natura ← `LineItem.exemption_reason`
  della prima riga del bucket, fallback `nature.default_exemption_reason`
- **DatiOrdineAcquisto / DatiContratto / DatiDDT / DatiFattureCollegate** ← `Invoice.references`
- **Allegati** ← `Invoice.attachments` (con `FormatoAttachment` dall'estensione
  e `DescrizioneAttachment`)
- **EsigibilitaIVA** ← `Invoice.exigibility` / `Invoice.split_payment`
- `ImportoPagamento` = `total_payable()` (totale al netto delle ritenute)

**Destinatari esteri** (convenzioni SdI): `CodiceDestinatario = "XXXXXXX"`
automatico quando `buyer.country_code != "IT"` senza codice esplicito; `CAP =
"00000"` quando il CAP estero non è di 5 cifre; `Provincia` omessa fuori
dall'Italia. Per la PA (`FPA12`) il codice destinatario è di 6 caratteri e
`validate()` ne verifica la lunghezza (7 per `FPR12`).

Non ancora coperto (estendibile): **Fattura semplificata** (schema diverso).

## Firma e trasmissione

L'XML prodotto **non è firmato**. Per SDI serve la firma qualificata CAdES
(`.xml.p7m`) o XAdES: la fanno i portali (vedi [TRANSPORT.md](TRANSPORT.md)),
oppure la integri come `Signer` nell'`EInvoiceEngine`. L'export su file
(`transport "file"`) genera l'XML da far firmare/caricare.

Per estendere: aggiungi i campi al dataclass (`models.py`) e il blocco
nell'ordine **esatto** dell'XSD (sequence-bound). `tests/test_fatturapa.py`
mostra come verificare struttura e totali.
