# Aliquote IVA e regole fiscali per paese

Un paese non ha «un'aliquota IVA». Ha un'aliquota ordinaria e qualche aliquota
ridotta, e quale si applica dipende da **cosa** si vende: in Italia un libro è al
4%, una notte d'albergo al 10%, un portatile al 22%. Sapere che il 4% esiste non
serve a niente; serve sapere che il libro ci va.

```python
from einvoice import ProductCategory, rate_for, profile_for

rate_for("IT", ProductCategory.BOOKS)                  # Decimal("4")
rate_for("DE", ProductCategory.BOOKS)                  # Decimal("7")
rate_for("GB", ProductCategory.CHILDRENS_CLOTHING)     # Decimal("0")
profile_for("CH").rate_for(ProductCategory.ACCOMMODATION)   # Decimal("3.8")
```

```bash
einvoice rates IT                    # tutte le aliquote e cosa coprono
einvoice rates DE --category books
einvoice rules IT                    # conservazione, soglie, termini
```

---

## Fin dove fidarsi

Questa è la parte del pacchetto che invecchia. Le **aliquote** in sé sono quelle
pubblicate e cambiano di rado; la **mappatura per categoria** è dove il diritto
nazionale si fa intricato — eccezioni, soglie, regimi transitori, e regole che
dipendono da dettagli che una fattura non porta (il libro è scolastico? il pasto
è consumato sul posto?).

Quindi, per scelta esplicita:

- tutto è datato da `RATES_VERIFIED_AS_OF` e `MANDATES_VERIFIED_AS_OF`, e la CI
  fallisce se quelle date superano l'anno;
- la copertura è **parziale di proposito**: una categoria che il pacchetto non
  sa dichiarare con certezza semplicemente non c'è, e `rate_for()` restituisce
  `None` invece di un'ipotesi;
- **niente di tutto questo rifiuta una fattura.** Alimenta `check()`, mai
  `validate()`.

È la risposta che ti darebbe un collega competente prima di sentire il
commercialista. Non è il commercialista.

## I tipi di aliquota

`RateKind` usa il vocabolario della direttiva IVA, perché il tipo conta
indipendentemente dal numero:

| Tipo | Cosa significa |
|---|---|
| `standard` | L'aliquota ordinaria. Si applica a tutto ciò che non rientra altrove. |
| `reduced` | Aliquota ridotta, applicabile all'elenco dell'Allegato III. |
| `super_reduced` | Sotto il 5%, ammessa solo per gli Stati che già la applicavano. |
| `parking` | Aliquota transitoria mantenuta da alcuni Stati per beni fuori Allegato III. |
| `zero` | Operazione **imponibile allo 0%**. Non è un'esenzione. |

### Zero non è esente

Distinzione che costa cara: entrambe mostrano 0 in fattura, ma

- **aliquota zero** = imponibile allo 0%: il venditore **detrae** l'IVA sugli
  acquisti;
- **esente** = fuori dal campo di applicazione: il diritto alla detrazione si
  **perde**.

Regno Unito e Irlanda applicano l'aliquota zero a un elenco ampio (alimentari,
libri, abbigliamento per bambini). `COMMONLY_EXEMPT` elenca invece le categorie
tipicamente esenti in UE — cure mediche, istruzione, servizi finanziari,
assicurazioni — e per quelle `rate_for()` restituisce `None` di proposito: non
hanno un'aliquota.

## Le categorie

`ProductCategory` prende il vocabolario dall'**Allegato III** della direttiva
IVA (come modificato dalla 2022/542), cioè l'elenco da cui gli Stati membri
possono scegliere. Una categoria esiste qui quando la fattura può plausibilmente
conoscerla: «abbigliamento per bambini» sì, «libro di natura educativa approvato
dal ministero» no.

Tre gruppi:

| Gruppo | Comportamento di `rate_for()` |
|---|---|
| Mappate in un paese | L'aliquota di quel paese |
| `ALWAYS_STANDARD_RATED` (alcolici, servizi digitali) | L'aliquota ordinaria |
| `COMMONLY_EXEMPT` (cure mediche, istruzione, finanza, assicurazioni) | `None` — sono esenti, non ridotte |

Nessuna categoria è «morta»: c'è un test che pretende che ognuna sia
raggiungibile in uno di questi tre modi. Una voce di vocabolario che non dà mai
una risposta sembra copertura e si comporta come un buco.

### Quando un paese spacca una categoria

Il Belgio applica lo 0% ai quotidiani e il 6% agli altri periodici — una
distinzione che la fattura non porta. In casi così la mappatura dà il **caso
generale** (6%) e l'eccezione sta scritta nella `note` dell'aliquota. Una
categoria non punta mai a due aliquote, altrimenti la risposta dipenderebbe
dall'ordine della tabella.

## Controllare una riga contro la sua categoria

`LineItem` ha un campo `category` **opzionale**. Non finisce in nessun XML —
nessuno standard di e-invoicing lo trasporta — e serve solo a far confrontare a
`check()` l'aliquota che hai usato con quella che il paese applica a quel tipo
di cessione:

```python
LineItem("Manuale di storia", 1, Decimal("30"), Decimal("22"),
         category=ProductCategory.BOOKS)

invoice.check()
# [rate_category] Riga 'Manuale di storia': aliquota 22% per 'books', ma IT
# applica di norma 4% a questa categoria. Verificare…
```

Se non dichiari la categoria non succede niente: il campo non costa nulla a chi
non lo usa. Se la categoria non è mappata per quel paese, silenzio — non un
reclamo.

## Le regole non-aliquota

`FiscalRules` raccoglie le domande che arrivano una volta che l'XML è corretto:

```python
rules = profile_for("IT").fiscal_rules
rules.retention_years                 # 10
rules.simplified_invoice_threshold    # Decimal("400")
rules.issue_deadline_days             # 12
rules.domestic_reverse_charge         # True
rules.notes                           # il contesto in parole
```

| Campo | Cosa risponde |
|---|---|
| `retention_years` | Per quanti anni va conservata la fattura |
| `simplified_invoice_threshold` | Sotto quale importo si può emettere una fattura semplificata (`TD07`/`TD08`/`TD09`) |
| `issue_deadline_days` | Entro quanti giorni dall'operazione va emessa |
| `domestic_reverse_charge` | Se esiste un'inversione contabile interna per settori specifici |
| `notes` | Ciò che un integratore deve sapere prima di fatturare lì |

`EU_OSS_THRESHOLD` sta a parte perché **non è per paese**: i 10.000 € delle
vendite a distanza sono un fatturato *complessivo* su tutti gli Stati membri, ed
è esattamente la parte che si sbaglia.

Come per le aliquote, un valore che il pacchetto non sa dichiarare è `None` e
non un numero plausibile: `profile_for("US").fiscal_rules.retention_years` è
`None` perché negli Stati Uniti la regola è statale.

## Gli Stati Uniti sono un caso a parte

Non c'è IVA federale. La sales tax è statale e locale, varia per giurisdizione e
per prodotto, e la determina il motore fiscale del venditore riga per riga.
`rates_for("US")` è vuoto e `NO_NATIONAL_VAT["US"]` spiega perché — invece di
inventare uno 0%, che avrebbe fatto sembrare un'anomalia ogni sales tax reale.

Di conseguenza `is_known_vat_rate()` accetta qualunque aliquota per gli USA: in
quella giurisdizione l'aliquota viene legittimamente da un posto che questo
pacchetto non modella.

## Riferimento rapido

```python
from einvoice import (
    ProductCategory, RateKind, rates_for, rate_for, standard_rate,
    categories_for, COMMONLY_EXEMPT, ALWAYS_STANDARD_RATED,
    NO_NATIONAL_VAT, RATES_VERIFIED_AS_OF, EU_OSS_THRESHOLD, profile_for,
)

standard_rate("HU")                     # Decimal("27") — la più alta in UE
standard_rate("LU")                     # Decimal("17") — la più bassa
rates_for("CH")                         # tutte le aliquote svizzere, con le categorie
categories_for("IE")                    # ogni categoria mappata per l'Irlanda
profile_for("PT").fiscal_rules.notes    # ATCUD, QR code, SAF-T
```

## Come si chiama l'identificativo fiscale

Ogni profilo porta il nome che il paese usa davvero — `USt-IdNr.` in Germania,
`NIP` in Polonia, `ΑΦΜ` in Grecia, `P.IVA` in Italia — perché un campo
etichettato «VAT» ovunque non è tanto sbagliato quanto inutile: chi cerca dove
inserire la propria partita IVA non dovrebbe doverlo indovinare.

```python
profile_for("DE").tax_id_label      # "USt-IdNr."
profile_for("US").tax_id_label      # "EIN" — non è affatto un'IVA
```

Serve anche nei messaggi di errore: la validazione nomina il campo come lo
nomina il paese, non come lo nomina questo pacchetto.

Per una UI, `einvoice.reference` restituisce lo stesso dato già in JSON —
vedi [ARCHITECTURE.md](ARCHITECTURE.md#dati-di-riferimento-per-una-ui).

Vedi anche [COUNTRIES.md](COUNTRIES.md) per la matrice paese per paese di
formati, obblighi e validazione dei tax-id.
