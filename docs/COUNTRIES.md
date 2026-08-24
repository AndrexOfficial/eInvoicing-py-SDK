# Paesi — matrice operativa

Trenta profili: i **27 stati UE**, il **Regno Unito**, la **Svizzera** e gli
**Stati Uniti**. Questa pagina è la vista d'insieme; il dettaglio per singolo
paese si legge dal codice, che è la fonte:

```bash
einvoice countries          # la tabella qui sotto, generata dal pacchetto
einvoice countries CH       # dettaglio completo, in JSON
```

> **Sui dati normativi.** Obblighi, reti e scadenze sono **guida operativa, non
> consulenza legale**. Sono datati da `MANDATES_VERIFIED_AS_OF` (esposto anche
> dalla CLI) perché le regole si muovono: verificare presso l'autorità fiscale
> nazionale prima di farne affidamento. Le parti meccaniche — validazione dei
> tax-id, aliquote, identificativi CIUS, regole di rendering — non invecchiano
> allo stesso modo.

## La tabella

| ISO | Paese | Formato | Rete | B2G | B2B | Tax-id | Aliquote | Valuta | Coperto |
|---|---|---|---|---|---|---|---|---|---|
| AT | Österreich | ubl | peppol | mandatory | voluntary | checksum | 20 / 13 / 10 | EUR | ✅ |
| BE | Belgique/België | ubl | peppol | mandatory | mandatory | checksum | 21 / 12 / 6 | EUR | ✅ |
| BG | България | ubl | peppol | mandatory | voluntary | structural | 20 / 9 | BGN | ✅ |
| CH | Schweiz/Suisse/Svizzera | ubl | peppol | mandatory | voluntary | checksum | 8.1 / 3.8 / 2.6 | CHF | ✅ |
| CY | Κύπρος | ubl | peppol | mandatory | voluntary | structural | 19 / 9 / 5 | EUR | ✅ |
| CZ | Česko | ubl | peppol | mandatory | voluntary | structural | 21 / 12 | CZK | ✅ |
| DE | Deutschland | ubl | peppol | mandatory | phased | checksum | 19 / 7 | EUR | ✅ |
| DK | Danmark | ubl | peppol | mandatory | voluntary | checksum | 25 | DKK | ✅ |
| EE | Eesti | ubl | peppol | mandatory | voluntary | checksum | 24 / 22 / 9 | EUR | ✅ |
| ES | España | ubl | facturae | mandatory | phased | structural | 21 / 10 / 4 | EUR | ⚠️ Facturae 3.2.x XML |
| FI | Suomi | ubl | peppol | mandatory | voluntary | checksum | 25.5 / 14 / 10 | EUR | ✅ |
| FR | France | ubl | chorus | mandatory | phased | checksum | 20 / 10 / 5.5 / 2.1 | EUR | ✅ |
| GB | United Kingdom | ubl | peppol | voluntary | voluntary | checksum | 20 / 5 | GBP | ✅ |
| GR | Ελλάδα | ubl | mydata | mandatory | phased | checksum | 24 / 13 / 6 | EUR | ✅ |
| HR | Hrvatska | ubl | peppol | mandatory | voluntary | checksum | 25 / 13 / 5 | EUR | ✅ |
| HU | Magyarország | ubl | rtir | mandatory | voluntary | checksum | 27 / 18 / 5 | HUF | ✅ |
| IE | Ireland | ubl | peppol | mandatory | voluntary | checksum | 23 / 13.5 / 9 / 4.8 | EUR | ✅ |
| IT | Italia | fatturapa | sdi | mandatory | mandatory | checksum | 22 / 10 / 5 / 4 | EUR | ✅ |
| LT | Lietuva | ubl | peppol | mandatory | voluntary | structural | 21 / 9 / 5 | EUR | ✅ |
| LU | Luxembourg | ubl | peppol | mandatory | voluntary | checksum | 17 / 14 / 8 / 3 | EUR | ✅ |
| LV | Latvija | ubl | peppol | mandatory | voluntary | structural | 21 / 12 / 5 | EUR | ✅ |
| MT | Malta | ubl | peppol | mandatory | voluntary | structural | 18 / 12 / 7 / 5 | EUR | ✅ |
| NL | Nederland | ubl | peppol | mandatory | voluntary | structural | 21 / 9 | EUR | ✅ |
| PL | Polska | ubl | ksef | mandatory | phased | checksum | 23 / 8 / 5 | PLN | ⚠️ KSeF FA(2) XML |
| PT | Portugal | ubl | peppol | mandatory | voluntary | checksum | 23 / 13 / 6 | EUR | ✅ |
| RO | România | ubl | efactura | mandatory | mandatory | structural | 21 / 11 | RON | ✅ |
| SE | Sverige | ubl | peppol | mandatory | voluntary | checksum | 25 / 12 / 6 | SEK | ✅ |
| SI | Slovenija | ubl | peppol | mandatory | voluntary | checksum | 22 / 9.5 / 5 | EUR | ✅ |
| SK | Slovensko | ubl | peppol | mandatory | voluntary | checksum | 23 / 19 / 5 | EUR | ✅ |
| US | United States | ubl | peppol | voluntary | voluntary | structural | — | USD | ✅ |

**Coperto** = i renderer di questo pacchetto producono ciò che il canale
nazionale accetta. `⚠️` segnala un paese il cui mandato richiede una sintassi
che **non** generiamo — è dichiarato in `profile.regime.national_format`, non
lasciato scoprire in produzione.

**Tax-id** = `checksum` se la cifra di controllo è verificata (un refuso viene
intercettato), `structural` se si verifica solo la forma. Vedi
[la sezione sui tax-id](#validazione-dei-tax-id).

## I casi che meritano attenzione

### Italia — SdI, non Peppol

L'unico paese in cui il default **non** è UBL: `renderer_for_country("IT")`
restituisce FatturaPA. Il B2B via SdI è obbligatorio dal 2019 e dal 2024 copre
anche i forfettari. Peppol resta usabile verso l'estero.

### Francia — la riforma vuole CII

Chorus Pro (B2G) e la riforma B2B ammettono Factur-X, UBL e CII. Factur-X è ciò
che il software francese scambia davvero, ed è **CII**, non UBL:

```python
renderer_for_country("FR", standard="cii")
```

### Germania — due mondi che convivono

B2G vuole **XRechnung** (`renderer_for_country("DE", b2g=True)`). Il B2B ammette
sia XRechnung sia **ZUGFeRD**, che è Factur-X sotto altro nome — quindi ancora
CII. Ricezione obbligatoria dal 2025-01-01, emissione in fasi fino al 2028.

### Svizzera — fuori UE, e conta

Non è nell'UE, quindi **non esistono cessioni intracomunitarie**: una vendita da
un paese UE verso la Svizzera è un'esportazione, e `check()` lo segnala se la
fattura espone IVA. L'identificativo è l'**UID CHE**, che è insieme partita IVA
e numero di registro di commercio, si valida con un mod-11 e **si usa così com'è**
sulla rete Peppol (EAS `0183`): ha già il suo prefisso `CHE`, aggiungere `CH`
produrrebbe `CHCHE…`.

Le `Natura` italiane sono rifiutate per un venditore svizzero: descrivono un
regime IVA che in Svizzera non esiste, e lasciarle passare produrrebbe un
documento che afferma il falso.

Il **QR-bill** è uno standard di **pagamento** domestico e resta separato dalla
fattura elettronica: non è un formato che questo pacchetto debba emettere.

### Polonia e Spagna — non coperte, e lo diciamo

- **KSeF** accetta solo il formato nazionale **FA(2)**.
- **FACe** accetta solo **Facturae 3.2.x**.

Nessuno dei due è UBL. Il pacchetto genera EN 16931 valido, ma per il mandato
domestico serve un convertitore o un provider che produca il formato nazionale
(B2Brouter ed EDICOM sono nei preset proprio per questo).

### Ungheria e Grecia — reporting, non fatturazione

NAV RTIR (HU) e myDATA (GR) sono obblighi di **trasmissione dati** paralleli
alla fattura, non formati di fattura. Il profilo lo annota; adempierli è fuori
dal perimetro di questo pacchetto.

### Regno Unito e Stati Uniti — nessun mandato

Nel Regno Unito Making Tax Digital riguarda i **registri IVA**, non il formato
della fattura; Peppol (EAS 9932) è usato dal NHS e da parte del settore
pubblico. Negli Stati Uniti non c'è mandato federale: l'imposta è **sales tax**
statale/locale (`STT`, non IVA) e la rete di interscambio è DBNAlliance.

## Validazione dei tax-id

Il check digit è verificato per **20 paesi**: AT, BE, CH, DE, DK, EE, FI, FR,
GB, GR, HR, HU, IE, IT, LU, PL, PT, SE, SI, SK.

Per gli altri la verifica è **strutturale**, e il profilo lo dichiara invece di
implicarlo:

```python
profile_for("ES").tax_id_validation   # "structural"
profile_for("DE").tax_id_validation   # "checksum"
```

I motivi sono documentati caso per caso in `einvoice/taxid.py`: algoritmi non
pubblicati (MT), varianti incompatibili in circolazione (BG, CZ, LT, LV, RO),
regole diverse per tipo di soggetto (ES), o l'assenza di una cifra di controllo
(NL dal 2020, EIN statunitense).

Nessuno dei due livelli prova che il numero **esista**: per quello serve una
lookup VIES / HMRC / registro UID, cioè una chiamata di rete — deliberatamente
fuori da un pacchetto il cui core è senza dipendenze.

Le forme stampate si normalizzano da sole:

```python
validate_tax_id("CH", "CHE-116.281.710 MWST")   # True
validate_tax_id("FR", "FR 40 303 265 045")      # True
validate_tax_id("GR", "EL094014249")            # True (ISO dice GR, VIES dice EL)
```

**Perché ogni algoritmo è ancorato a un numero reale.** Rifiutare la partita IVA
di un cliente vero blocca una fattura legittima; accettare un refuso la fa
scartare a valle. Il primo danno è peggiore, quindi ogni checksum è pinnato in
`tests/test_taxid.py` contro un identificativo pubblicato e realmente in uso —
quattro di questi algoritmi erano sbagliati alla prima stesura e sono quei test
ad averlo rivelato.

## Aliquote IVA

`profile.vat_rates` elenca le aliquote in vigore, e `is_known_vat_rate()` dice
se una è fra quelle. Serve a `check()` per intercettare il refuso classico —
`2.2` al posto di `22` — ma **non blocca mai** un documento: regimi speciali,
aliquote transitorie ed eccezioni locali sono troppi per essere enumerati, e un
errore bloccante qui fermerebbe fatture valide.

Quale aliquota si applica a **cosa** — libri, alberghi, alimentari, farmaci — sta
in [TAXES.md](TAXES.md), insieme alle regole non-aliquota (conservazione, soglie
per la fattura semplificata, termini di emissione, reverse charge interno).

```bash
einvoice rates IT
einvoice rules IT
```
