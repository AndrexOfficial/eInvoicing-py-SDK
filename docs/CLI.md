# CLI e formato JSON

Due facce della stessa cosa: `einvoice.serde` definisce **una forma JSON
portabile** per il modello di dominio, e la CLI è il modo di lavorarci sopra da
shell — validare, calcolare i totali, generare l'XML, firmarlo.

Serve a controllare la risposta del motore contro le attese di un
commercialista **senza tirare su un'applicazione**: stampa esattamente i byte
che un transport spedirebbe.

---

## La riga di comando

```bash
pip install einvoice        # installa anche il comando `einvoice`
einvoice --help
python -m einvoice --help   # equivalente, senza dipendere dal PATH
```

| Comando | Cosa fa |
|---|---|
| `validate FILE` | Valida secondo le regole del paese del cedente e stampa i totali |
| `check FILE` | Rilievi **non bloccanti** (aliquote, regimi, date). `--strict` per uscire con 1 |
| `parse FILE` | Legge una fattura **ricevuta** (XML) e la restituisce in JSON (`--standard`, `-o`) |
| `inspect FILE` | Riepiloga un documento ricevuto; esce **1** se il totale dichiarato contraddice le righe |
| `totals FILE` | Riepiloghi IVA calcolati, in JSON |
| `render FILE` | Genera l'XML (`--standard`, `--country`, `--xrechnung`, `-o`) |
| `normalize FILE` | Riscrive il JSON in forma canonica |
| `sign FILE.xml` | Firma CAdES `.p7m` (`--p12`, `--passphrase`, `-o`) |
| `countries [CODE]` | Elenca o descrive i profili paese: formato, rete, obblighi B2G/B2B, forza della validazione, aliquote (`--tax-id` per verificarne uno) |
| `rates CC` | Aliquote IVA di un paese e cosa coprono (`--category` per una sola) |
| `rules CC` | Obblighi non-aliquota: conservazione, soglie, termini, reverse charge |
| `providers [KEY]` | Piattaforme di e-invoicing (`--country`, `--kind`, `--kinds`, `--setup`, `--lang`) |
| `transports` | Elenca i canali registrati |
| `renderers [KEY]` | Descrive i formati documentali (`--country`, `--lang`) |
| `locales` | Lingue disponibili per le etichette di setup |

`FILE` può essere `-` per leggere da stdin, così la CLI si compone in pipeline.

### Exit code

| Codice | Significato |
|---|---|
| `0` | Riuscito |
| `1` | Input non valido — fattura rifiutata, JSON malformato, firma fallita |
| `2` | Uso errato della CLI — opzione o comando inesistente |

La distinzione è deliberata: in CI **un rilievo fiscale non va confuso con un
typo nel comando**. `validate` che esce `1` è il tool che funziona; `2` vuol
dire che la pipeline stessa è sbagliata.

### Esempi

```bash
# La fattura passa le regole SdI?
einvoice validate fattura.json

# I numeri che controlla il commercialista
einvoice totals fattura.json

# L'XML esatto che verrebbe trasmesso
einvoice render fattura.json -o IT01234567890_00001.xml

# Un cedente tedesco B2G: UBL con CIUS XRechnung, non FatturaPA
einvoice render fattura-de.json --country DE --xrechnung

# Un cedente francese: CII / Factur-X, la sintassi che Chorus Pro scambia
einvoice render fattura-fr.json --standard cii -o FR.xml

# Cosa merita un occhio umano prima di spedire
einvoice check fattura.json

# Cosa serve per un paese, e quali piattaforme lo servono
einvoice countries CH
einvoice providers --country CH
einvoice providers --kinds
einvoice providers aruba --setup --lang de   # istruzioni di configurazione
einvoice renderers --country FR --lang fr    # i formati che la Francia accetta

# Il ciclo passivo: cosa è arrivato, e se i conti tornano
einvoice inspect ricevuta.xml
einvoice parse   ricevuta.xml -o ricevuta.json
einvoice validate ricevuta.json

# Firma qualificata
einvoice sign IT01234567890_00001.xml --p12 firma.p12 --passphrase '…'

# Verifica di una partita IVA — con cifra di controllo dove esiste
einvoice countries DE --tax-id DE136695976
einvoice countries CH --tax-id "CHE-116.281.710 MWST"
```

---

## Il formato JSON

Tre regole, e sono tutte deliberate.

**1. I nomi dei campi sono quelli delle dataclass.** Non c'è una tabella di
corrispondenza da consultare: `Invoice.number` è `"number"`, `Party.vat_number`
è `"vat_number"`.

**2. Gli importi sono stringhe, mai float.** `0.1 + 0.2 != 0.3` è esattamente la
classe di errore che rende una fattura sbagliata di un centesimo e la fa
scartare a valle. I numeri JSON *sono accettati* in ingresso — passano da
`Decimal(str(...))`, quindi restano esatti — perché scrivere fixture a mano
deve restare comodo; in uscita però si scrivono sempre stringhe.

**3. Gli enum viaggiano col loro codice di standard.** `TD01`, `MP05`, `N2.2`,
`RF19`: è la stessa stringa che finisce nell'XML, quindi il JSON si legge con
la documentazione dell'Agenzia delle Entrate accanto.

I campi opzionali omessi mantengono il default della dataclass, perciò la
fattura valida più piccola è davvero piccola.

### Minimo indispensabile

```json
{
  "number": "2026/0001",
  "date": "2026-06-05",
  "seller": {
    "name": "Trattoria da Mario",
    "vat_number": "01234567890",
    "address": {"street": "Via Roma 1", "postcode": "20100", "city": "Milano", "province": "MI"}
  },
  "buyer": {
    "name": "ACME Srl",
    "vat_number": "09876543210",
    "sdi_code": "ABCDEFG",
    "address": {"street": "Via Verdi 9", "postcode": "00100", "city": "Roma", "province": "RM"}
  },
  "lines": [
    {"description": "Cena", "quantity": "1", "unit_price": "100.00", "vat_rate": "22"}
  ]
}
```

### Prezzi al lordo (POS, ristorazione, retail)

FatturaPA e UBL ragionano sull'**imponibile**, ma una cassa conosce il prezzo
IVA inclusa. Su una riga si indica `gross_unit_price` al posto di `unit_price` e
lo scorporo avviene esattamente come in `LineItem.from_gross`:

```json
{"description": "Menu degustazione", "quantity": "2", "gross_unit_price": "55.00", "vat_rate": "10"}
```

Indicare **entrambi** è un errore, non una precedenza silenziosa: significa che
a monte c'è un vero problema di prezzo, e nasconderlo lo farebbe arrivare in
fattura.

### Blocchi opzionali

Tutti facoltativi; si impostano solo quando servono.

| Campo | Tipo | Note |
|---|---|---|
| `document_type` | `"TD01"`…`"TD28"` | Default `TD01`. `TD04`/`TD08` = nota di credito, `TD05`/`TD09` = nota di debito — vedi [CORRECTIONS.md](CORRECTIONS.md) |
| `causale` | stringa | Causale del documento |
| `currency` | stringa | Default `"EUR"` |
| `payments[]` | `means`, `amount`, `due_date`, `condition`, `account{iban,bic,…}` | `means` = `MP01`…`MP23` |
| `allowances_charges[]` | `amount`, `is_charge`, `vat_rate`, `reason` | Sconti/maggiorazioni di documento |
| `lines[].discounts[]` | idem | Sconti di linea |
| `withholdings[]` | `amount`, `rate`, `kind`, `reason` | Ritenuta d'acconto |
| `funds[]` | `kind` (`TC01`…), `rate`, `amount`, `vat_rate` | Cassa previdenziale |
| `stamp_duty` | importo | Bollo virtuale (es. `"2.00"`) |
| `references[]` | `kind` (`order`/`contract`/`ddt`/`invoice`), `doc_id`, `date` | Documenti collegati |
| `attachments[]` | `filename`, `content_base64`, `mime` | Allegati |
| `split_payment` | bool | Scissione dei pagamenti (PA) |
| `exigibility` | `"I"`/`"D"`/`"S"` | Override esigibilità IVA |
| `art73`, `rounding`, `buyer_reference`, `payment_terms_note` | | |

Righe: oltre a `description`/`quantity`/prezzo/`vat_rate` accettano
`unit_of_measure`, `nature` (`N1`…`N7.x`, obbligatoria in Italia con aliquota 0),
`article_code`, `period_start`/`period_end`, `exemption_reason` e `category`
(categoria merceologica: alimenta solo `check()`, non finisce in nessun XML —
vedi [TAXES.md](TAXES.md)).

### Errori

La decodifica indica **il percorso** del campo colpevole, non solo il tipo di
problema:

```
errore: lines[1].unit_price: importo non valido ('cento')
errore: invoice.date: data non valida ('05/06/2026'), attesa YYYY-MM-DD
errore: document_type: 'TD99' non valido. Ammessi: TD01, TD02, …
```

### Round-trip

`invoice_to_dict` → `invoice_from_dict` è senza perdite per tutto ciò che i
renderer leggono (gli allegati passano da base64). Utile per fixture di
regressione: `einvoice normalize` produce la forma canonica, e due fixture
equivalenti scritte in modo diverso diventano diffabili.

```python
from einvoice import invoice_from_json, invoice_to_json

restored = invoice_from_json(invoice_to_json(invoice))
assert restored.total_document() == invoice.total_document()
```
