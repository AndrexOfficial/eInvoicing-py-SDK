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
- **ScontoMaggiorazione di linea** ← `LineItem.discounts`. Attenzione: nel
  modello lo sconto di riga è un importo **sul totale della riga** (come in
  EN 16931), in FatturaPA è **per unità** — SdI ricalcola
  `PrezzoTotale = (PrezzoUnitario − ΣSconti + ΣMaggiorazioni) × Quantita`
  (controllo **00423**, tolleranza 1 centesimo). Il renderer divide per la
  quantità (fino a 8 decimali) e rifà il calcolo di SdI sui valori scritti
  prima di restituire il file: se non torna solleva `RenderError` invece di
  produrre uno scarto. Prima della 0.10.0 lo sconto veniva scritto come totale
  di riga: con quantità diversa da 1 il file era scartato.
- **RiferimentoNormativo** nei `DatiRiepilogo` con Natura ← `LineItem.exemption_reason`
  della prima riga del bucket, fallback `nature.default_exemption_reason`
- **DatiOrdineAcquisto / DatiContratto / DatiFattureCollegate / DatiDDT** ←
  `Invoice.references`, sempre nell'ordine della sequence XSD qualunque sia
  l'ordine del chiamante (prima della 0.10.0 lo seguiva, e una nota di credito
  con fattura collegata e ordine era scartata). `DatiDDT` ha una forma sua:
  `NumeroDDT`, `DataDDT` (**obbligatoria**), poi le `RiferimentoNumeroLinea`
  — non `IdDocumento`/`Data` come gli altri riferimenti, che è come lo scriveva
  il pacchetto prima della 0.10.0. Il parser rilegge anche quella forma vecchia.
- **DatiTrasporto** ← `Invoice.transport` (`TransportDetails`): la *fattura
  accompagnatoria*. Vettore (solo se ha P.IVA: `IdFiscaleIVA` è obbligatorio nel
  blocco), mezzo, causale nella lingua del cedente, colli, aspetto, pesi, data e
  ora del ritiro/inizio trasporto, resa Incoterms, indirizzo di resa. Vedi
  [DOCUMENTS.md](DOCUMENTS.md).
- **Allegati** ← `Invoice.attachments` (con `FormatoAttachment` dall'estensione
  e `DescrizioneAttachment`)
- **EsigibilitaIVA** ← `Invoice.exigibility` / `Invoice.split_payment`
- `ImportoPagamento` = `total_payable()` (totale al netto delle ritenute)

**Destinatari esteri** (convenzioni SdI): `CodiceDestinatario = "XXXXXXX"`
automatico quando `buyer.country_code != "IT"` senza codice esplicito; `CAP =
"00000"` quando il CAP estero non è di 5 cifre; `Provincia` omessa fuori
dall'Italia. Per la PA (`FPA12`) il codice destinatario è di 6 caratteri e
`validate()` ne verifica la lunghezza (7 per `FPR12`).

## Quello che lo schema e SdI pretendono (0.10.0)

Il renderer è validato in test contro lo **schema ufficiale 1.2.3**
(`tests/schemas/fatturapa`, specifiche tecniche 1.9) su una matrice di fatture:
ogni tipo documento, ogni natura IVA, riferimenti in ogni ordine, DDT multipli,
trasporto, PA, estero, resi, sconti, testi tipografici. Le regole che ne sono
uscite:

- **Testo solo Latin-1** (`String…LatinType`; alcuni campi solo ASCII). Tutti i
  campi di testo passano da `einvoice.formats.latin.to_latin`: la tipografia si
  riscrive (’ → ', – → -, … → ..., € → EUR), le lettere si piegano quando si
  può (ł → l, ș → s, ő → o), le decorazioni cadono (emoji), e le lettere senza
  grafia latina (cirillico, greco, CJK, thai) **fermano** il documento con un
  errore che nomina campo e caratteri — mai punti interrogativi. Lunghezze
  massime per campo, misurate dopo la riscrittura.
- **Causale** oltre 200 caratteri → più elementi `Causale` (lo schema li ammette
  0..N), spezzati sugli spazi; il parser li ricongiunge.
- **Quantità mai negative** (`QuantitaType` non ha segno): un reso su riga
  negativa esce come quantità positiva a prezzo negativo — stesso importo.
  Quantità fino a 8 decimali: 1,125 kg non diventa più «1.13».
- **IBAN e BIC** senza spazi e in maiuscolo; **codice fiscale** in maiuscolo;
  **IscrizioneREA** letta come «PR-NUMERO» (l'Ufficio deve essere la sigla della
  provincia: un REA illeggibile è un errore, non un file invalido).
- **Beneficiario** è il **primo** elemento di `DettaglioPagamento` (prima della
  0.10.0 era scritto dopo l'importo, dove lo schema lo rifiuta).
- **Partita IVA** scritta normalizzata (senza prefisso paese né spazi).

Controlli di contenuto SdI riprodotti in `validate()` (profilo IT), con il loro
codice: **00425** numero senza cifre (e al massimo 20 caratteri ASCII),
**00418** documento anteriore alla fattura collegata, **00471** cedente uguale
al cessionario per TD01/02/03/06/16–20/24/25/28, DDT senza data.

Non coperto: **fattura semplificata** (TD07–TD09, schema FSM10). Il renderer
ordinario la **rifiuta** con `RenderError`: prima scriveva un tipo che il
tracciato FPR12 non ammette.

## Firma e trasmissione

L'XML prodotto **non è firmato**. Per SDI serve la firma qualificata CAdES
(`.xml.p7m`) o XAdES: la fanno i portali (vedi [TRANSPORT.md](TRANSPORT.md)),
oppure la integri come `Signer` nell'`EInvoiceEngine`. L'export su file
(`transport "file"`) genera l'XML da far firmare/caricare.

Per estendere: aggiungi i campi al dataclass (`models.py`) e il blocco
nell'ordine **esatto** dell'XSD (sequence-bound). `tests/test_fatturapa.py`
mostra come verificare struttura e totali.
