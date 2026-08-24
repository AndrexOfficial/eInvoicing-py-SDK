# einvoice

**Motore di e-invoicing multicanale, standalone e riutilizzabile.**

Un dominio fiscale pulito (modello unico + stati + notifiche + audit), separato
dai formati nazionali e dai canali di trasporto. Italia-first (FatturaPA/SdI),
con UBL/EN 16931 e PEPPOL nel motore e **profili paese** per UE-27, Regno Unito
e Stati Uniti.

## Tre livelli (mix & match)

```
        ┌──────────────────────── EInvoiceEngine ────────────────────────┐
        │  validate → render → [sign] → transmit → [archive] → state/audit│
        └─────────────────────────────────────────────────────────────────┘
core domain (no deps)        formats / renderers           transport / channels
Invoice + Lifecycle    →     fatturapa · ubl(peppol)  →     file · fattureincloud
+ country profiles           (+ XRechnung CIUS, US            aruba · zucchetti
(EN16931-aligned,             sales tax; estendibili:         peppol · sdi
 stati + audit + esiti)       cii, zugferd)
```

| Livello | Dipendenze | Cosa fa |
|---|---|---|
| **Core** | nessuna | Modello fattura unico (EN 16931-aligned) + **profili paese** (UE-27/UK/US: regole, formati tax-id) + **macchina a stati** + notifiche normalizzate (esiti SdI/PEPPOL) + audit trail. |
| **Formats** | nessuna | Renderer per standard: **FatturaPA** (IT/SdI), **UBL Peppol BIS** (EN 16931, CIUS XRechnung, schema sales-tax US). |
| **Transport** | `httpx` (opz.) | Canali: file export, FattureInCloud, Aruba, Zucchetti, **PEPPOL Access Point**, con firma/conservazione/notifiche pluggable. |
| **Signing** | `cryptography` (opz.) | Firma **CAdES `.p7m`** (PKCS#7/CMS attached, SHA-256) da certificato PKCS#12 + pacchetto di **conservazione** (ZIP + manifest hash + indice IPdA-like). |

### Cosa è supportato

**Italia (FatturaPA 1.2.2 / SdI)** — liste codici complete: `TipoDocumento`
TD01–TD06 + TD16–TD28 (inclusa la **TD24 differita** per la ristorazione),
`Natura` N1–N7 con i sotto-codici puntati post-2021, `ModalitaPagamento`
MP01–MP23, `RegimeFiscale` validato (RF01–RF20). Blocchi: ritenuta, bollo,
**cassa previdenziale**, sconto/maggiorazione di documento **e di linea**,
codice articolo, periodo di competenza, esigibilità I/D/S, arrotondamento,
Art73, riferimento normativo nei riepiloghi, riferimenti (ordine/contratto/
DDT/fatture collegate), allegati con formato/descrizione, convenzioni per
destinatari esteri (`XXXXXXX`, CAP `00000`).

**Europa (EN 16931 / UBL Peppol BIS 3.0)** — root dedicata **CreditNote** per
le note di credito, `BuyerReference`/`OrderReference` sempre presenti
(PEPPOL-EN16931-R003), `EndpointID` con schema EAS derivato dalla P.IVA per
paese (tutta l'UE: IT 0211, DE 9930, FR 9957, … + GB 9932; Grecia con prefisso
VIES `EL` automatico), categorie IVA S/Z/E/AE/K/G/O mappate dalla `Natura` con
`TaxExemptionReason`, allowance/charge di documento e di linea, bollo e cassa
resi come charge per far quadrare BR-CO-10/13/15, `PayableRoundingAmount`,
`PaymentID` e `PaymentTerms`. **Germania B2G**: CIUS **XRechnung 3.0** via
`renderer_for_country("DE", xrechnung=True)`.

**Profili paese (`einvoice.countries`)** — un `CountryProfile` per i **27 stati
UE + UK + US**: standard di default del venditore (IT → fatturapa, altri →
ubl), pattern strutturali del tax-id (P.IVA VIES per l'UE, VAT Reg. GB, **EIN**
US), schema d'imposta (VAT / **STT** sales tax) e regole di validazione
per-paese — i vincoli italiani (RegimeFiscale, CodiceDestinatario, CAP, Natura)
si applicano SOLO ai venditori IT, quindi lo stesso `Invoice` neutro valida
anche per un venditore tedesco, britannico o americano.

**Regno Unito** — fattura UBL EN 16931 con VAT GB (nessun obbligo e-invoice:
MTD copre i registri IVA); Peppol via EAS 9932.

**Stati Uniti** — fattura UBL in stile EN 16931 con **sales tax** (UN/ECE 5153
`STT`), EIN come identificativo (senza prefisso), nessuna Natura IVA ammessa;
pronta per l'interscambio DBNAlliance.

## Installazione

```bash
pip install einvoice                # core + formats (export XML) — ZERO dipendenze
pip install "einvoice[providers]"   # + transport di rete (httpx)
pip install "einvoice[signing]"     # + firma CAdES .p7m (cryptography)
pip install "einvoice[all]"         # tutto
```

Il core è **stdlib pura**: `pip install einvoice` non tira dentro nulla, e la
CI lo verifica installando il pacchetto nudo e generando un XML con `httpx` e
`cryptography` assenti. L'installazione espone anche il comando `einvoice`.

## Uso 1 — solo XML (qualsiasi sistema)

```python
from datetime import date
from decimal import Decimal
from einvoice import Invoice, Party, Address, LineItem, build_fattura_xml, build_ubl_xml

inv = Invoice(
    number="2026/0001", date=date(2026, 6, 5),
    seller=Party(name="Trattoria da Mario", vat_number="01234567890",
                 address=Address("Via Roma 1", "20100", "Milano", "MI")),
    buyer=Party(name="ACME Srl", vat_number="09876543210",
                address=Address("Via Verdi 9", "00100", "Roma", "RM"), sdi_code="ABCDEF1"),
    lines=[LineItem.from_gross("Cena", 1, Decimal("122.00"), 22)],
)
xml_it = build_fattura_xml(inv)   # FatturaPA (SdI)
xml_eu = build_ubl_xml(inv)       # UBL Peppol BIS (EN 16931)
```

## Uso 2 — profili paese (UE / UK / US)

```python
from einvoice import profile_for, renderer_for_country, validate_tax_id

validate_tax_id("DE", "DE811193231")      # True (VIES strutturale)
validate_tax_id("US", "12-3456789")       # True (EIN)

renderer_for_country("IT")                    # FatturaPARenderer
renderer_for_country("DE", xrechnung=True)    # UBL con CIUS XRechnung 3.0
renderer_for_country("US")                    # UBL con TaxScheme STT (sales tax)

profile_for("GB").notes                   # note operative per paese
```

`Invoice.validate()` applica automaticamente le regole del paese del venditore:
un venditore US con righe a sales tax valida senza Nature/RegimeFiscale; un
venditore IT resta vincolato a tutte le regole SdI.

## Uso 3 — motore (render + invio + stato)

```python
from einvoice import EInvoiceEngine
from einvoice.formats import get_renderer
from einvoice.transport import get_transport, TransportConfig

engine = EInvoiceEngine(
    renderer=get_renderer("fatturapa"),                 # o "ubl" per PEPPOL
    transport=get_transport("aruba", TransportConfig(   # o "peppol", "file", …
        name="aruba", username="...", password="...", sandbox=True)),
)
result = await engine.process(inv)
result.lifecycle.state            # sent / delivered / accepted / rejected …
result.lifecycle.audit_trail()    # storia immutabile per audit
```

Cambiare formato o canale = cambiare una stringa. Le notifiche asincrone (esiti)
avanzano la stessa macchina a stati: `lifecycle.apply(notification)`.

## Uso 4 — JSON e riga di comando

Il modello è il confine d'integrazione: una piattaforma ci mappa sopra le sue
tabelle. `einvoice.serde` dà a quel modello **una forma JSON portabile**, così
una fattura può essere una fixture, un payload di coda o un record di audit —
e la CLI lavora direttamente su quel formato.

```python
from einvoice import invoice_to_json, invoice_from_json

payload = invoice_to_json(inv)        # importi come stringhe, enum come codici
same = invoice_from_json(payload)     # round-trip senza perdite
```

Gli importi viaggiano come **stringhe**, mai float (`0.1 + 0.2` è esattamente
l'errore che una fattura non può contenere), e gli enum come il loro codice di
standard: `TD01`, `MP05`, `N2.2`. Gli errori di decodifica indicano il punto
esatto — `lines[1].unit_price` — invece di fallire genericamente.

```bash
einvoice validate fattura.json          # valida + stampa i totali
einvoice totals fattura.json            # riepiloghi IVA calcolati (JSON)
einvoice render fattura.json -o IT.xml  # FatturaPA
einvoice render fattura.json --country DE --xrechnung
einvoice normalize fattura.json         # forma canonica, per diffare fixture
einvoice sign IT.xml --p12 cert.p12 --passphrase ...
einvoice countries IT --tax-id 01234567890
einvoice transports                     # canali disponibili
```

Serve a controllare la risposta del motore contro le attese di un
commercialista **senza tirare su un'applicazione**: stampa esattamente i byte
che un transport spedirebbe. Gli exit code separano *fattura non valida* (`1`)
da *comando sbagliato* (`2`), così in CI un rilievo non si confonde con un typo.

## Firma CAdES + conservazione

```python
from einvoice import sign_cades, build_conservation_package

p7m = sign_cades(xml_it, p12_bytes, passphrase)   # .p7m attached, SHA-256
zip_bytes = build_conservation_package(documents) # ZIP + manifest + pdd_index
```

## Documentazione

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — i 3 livelli, engine, stati, matrice EU, roadmap
- [docs/RENDERERS.md](docs/RENDERERS.md) — formati (FatturaPA, UBL/EN16931), come aggiungerne
- [docs/TRANSPORT.md](docs/TRANSPORT.md) — canali, firma, conservazione, notifiche
- [docs/FATTURAPA.md](docs/FATTURAPA.md) — mappatura IT, campi, codici
- [docs/INTEGRATION.md](docs/INTEGRATION.md) — integrazione in una piattaforma
- [docs/CLI.md](docs/CLI.md) — riga di comando e formato JSON (riferimento campi)
- [CONTRIBUTING.md](CONTRIBUTING.md) — regole di progetto (core senza dipendenze, Decimal, profili paese)
- [CHANGELOG.md](CHANGELOG.md) — cronologia versioni

## Test

```bash
pip install -e ".[dev]"
pytest -q          # 157 test, ~1 s
ruff check .
```

## Avvertenze

- **Firma CAdES** `.p7m`: `sign_cades(...)` produce PKCS#7 SignedData DER
  *attached* SHA-256 da un PKCS#12 di **firma qualificata**. Nota: manca
  l'attributo ETSI `signing-certificate-v2` di CAdES-BES — per conformità
  garantita usare un servizio di firma accreditato (vedi `einvoice/signer.py`).
- **Conservazione a norma**: `build_conservation_package(...)` genera lo ZIP
  di export (file + `manifest.json` con hash + `pdd_index.xml` IPdA-like) da
  consegnare a un **conservatore accreditato**; `WebhookConservationProvider`
  lo POSTa a un URL configurato. `FileArchive` resta un default dev/audit, NON
  conservazione certificata.
- I pattern tax-id dei profili paese sono **strutturali** (formato VIES/EIN),
  non verificano il checksum né l'esistenza: per quello serve una lookup VIES /
  IRS.
- I path API di **Aruba/Zucchetti/PEPPOL** hanno la struttura corretta ma vanno
  confermati sul tuo account (override via `base_url`/`extra`, testa in sandbox).
- **InfoCert, Notartel, Wolters Kluwer** e gli altri intermediari girano sul
  `GenericHubTransport`, configurabile (`upload_path`, `content_field`,
  `auth_scheme`, …): sono tutti la stessa forma REST con nomi diversi, e la
  configurazione batte un modulo scritto contro un contratto che non possiamo
  testare. Servono almeno `base_url` e una credenziale.

MIT.
