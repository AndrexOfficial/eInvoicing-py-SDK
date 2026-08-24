# Note di credito, note di debito e resi

Una rettifica è il documento che si sbaglia più facilmente, perché il suo
significato vive in due posti insieme: il **tipo documento** dice in che verso si
muovono i soldi, gli **importi** dicono quanto. Applicare il verso in tutti e due
i posti produce una nota di credito che chiede al cliente di pagare.

Questa pagina dice come si costruiscono, cosa fa il pacchetto per conto tuo, e
quali sono le due forme legittime di un reso.

---

## La regola che conta: gli importi sono POSITIVI

```python
nota = Invoice(
    number="NC-1", date=date(2026, 8, 24),
    document_type=DocumentType.CREDIT_NOTE,          # ← il verso sta QUI
    lines=[LineItem("Reso merce", 2, Decimal("50"), 22)],   # ← importi positivi
    references=[DocumentReference("invoice", "FT-9", date(2026, 7, 1))],
    seller=..., buyer=...,
)
nota.total_document()      # 122.00, positivo
```

Una nota di credito da 122,00 **dichiara 122,00**. Chi la legge sa dal tipo
documento che riduce quanto è dovuto. Vale per EN 16931 e per FatturaPA allo
stesso modo.

Se metti gli importi negativi il verso si applica due volte e il documento dice
l'opposto di quello che intendi. Il pacchetto se ne accorge:

```python
sbagliata.check()
# [correction_sign] Nota di credito con totale negativo (-122.00). Il verso è
# già dato dal tipo documento: gli importi vanno indicati POSITIVI…
```

È un **rilievo**, non un errore bloccante: esistono casi legittimi di riga
negativa dentro una rettifica (una correzione parziale che ri-addebita una
voce). Quello che non è mai legittimo è il *totale* negativo.

## Dire cosa si sta rettificando

```python
references=[DocumentReference("invoice", "FT-9", date(2026, 7, 1))]
```

Senza questo riferimento il destinatario non può abbinare la nota a niente: resta
nel suo partitario, non applicata. SdI e la gran parte dei CIUS **accettano**
comunque il documento, quindi anche qui è un rilievo e non un errore:

```
[correction_no_reference] Nota di credito senza riferimento alla fattura che
rettifica: il destinatario non può abbinarla.
```

Come finisce nei tre formati:

| Formato | Elemento |
|---|---|
| FatturaPA | `DatiGenerali/DatiFattureCollegate` (`IdDocumento` + `Data`) |
| UBL | `cac:BillingReference/cac:InvoiceDocumentReference` |
| CII | `ram:InvoiceReferencedDocument` |

## Note di credito e note di debito non sono la stessa cosa col segno girato

Entrambe rettificano una fattura precedente, in versi opposti, e **finiscono su
strutture diverse**:

| | Tipo IT | UNCL 1001 | Radice UBL | Righe UBL |
|---|---|---|---|---|
| Nota di credito | `TD04`, `TD08` | `381` | `CreditNote` | `cac:CreditNoteLine` / `cbc:CreditedQuantity` |
| Nota di debito | `TD05`, `TD09` | `383` | `Invoice` | `cac:InvoiceLine` / `cbc:InvoicedQuantity` |

Non è un dettaglio cosmetico: UBL 2.1 ha uno **schema separato** per le note di
credito. Emettere una radice `Invoice` con codice 381 produce un documento che
nessun destinatario Peppol accetta. Il pacchetto lo sceglie da sé leggendo
`DocumentType.is_credit_note`; tu non devi fare nulla.

CII invece ha una radice sola: cambia solo il `TypeCode`. È esattamente il motivo
per cui è facile sbagliarlo scrivendolo a mano.

Un dettaglio che UBL impone e che è facile mancare: la radice `CreditNote` **non
ha** `cbc:DueDate`. Se passi una scadenza di pagamento su una nota di credito, il
pacchetto la omette dal livello documento e mantiene il `PaymentMeans`.

## La famiglia «semplificata»

FatturaPA definisce anche i documenti semplificati, per gli importi sotto soglia
in cui il cessionario può essere identificato con la sola partita IVA:

| Codice | Documento | È nota di credito? |
|---|---|---|
| `TD07` | Fattura semplificata | no |
| `TD08` | **Nota di credito semplificata** | **sì** |
| `TD09` | Nota di debito semplificata | no (è di debito) |

«Semplificata» descrive quanto poco serve identificare il cliente, **non** cosa
fa il documento: una `TD08` riduce il dovuto esattamente come una `TD04`, e
finisce sulla stessa radice `CreditNote`.

> Fino alla 0.4.0 queste tre mancavano del tutto dal code list.
> `TD08` era il problema serio: una nota di credito che il pacchetto non sapeva
> essere tale.

**Attraverso EN 16931 il codice si restringe.** UNCL 1001 ha tre codici dove
l'Italia ne ha nove, quindi «semplificata» non sopravvive a un giro in UBL o CII:

```
TD07 → TD01      TD08 → TD04      TD09 → TD05
```

Quello che sopravvive sempre è il **verso**: una nota di credito torna una nota
di credito. FatturaPA conserva il codice esatto. Stessa classe di perdita
dichiarata dei sotto-codici `Natura` — vedi [PARSING.md](PARSING.md).

## I resi: due forme, entrambe corrette

Un reso si documenta in due modi, e il pacchetto tratta tutti e due come normali.

### 1. Nota di credito

La forma canonica quando la fattura originale è già stata emessa e magari
pagata.

```python
Invoice(document_type=DocumentType.CREDIT_NOTE,
        lines=[LineItem("Reso 2 di 10 pezzi", 2, Decimal("100"), 22)],
        references=[DocumentReference("invoice", "FT-9", date(2026, 7, 1))], …)
```

Una nota parziale sta in piedi da sola, al **proprio** importo: crediti 2 pezzi
su 10, la nota vale 244,00 e non ha bisogno di sapere quanto valeva la fattura.

### 2. Riga negativa sulla fattura successiva

Quando il reso si compensa con nuove forniture, invece di emettere una nota si
mette in fattura una riga negativa:

```python
lines=[
    LineItem("Vendita", 10, Decimal("100"), 22),
    LineItem("Reso",    -2, Decimal("100"), 22),   # quantità negativa
]
# imponibile 800,00 — totale 976,00
```

Questa **non** è una rettifica: il documento resta una `TD01`, e nessun rilievo
scatta. Quantità negative, prezzi negativi e un totale che arriva a zero sono
tutti gestiti e coperti dai test, in tutti e tre i formati.

### Quale scegliere

| Situazione | Forma |
|---|---|
| La fattura è già stata trasmessa e va rettificata | Nota di credito |
| Servono la tracciabilità e il riferimento al documento originale | Nota di credito |
| Il reso si compensa con nuove forniture nello stesso periodo | Riga negativa |
| Il cliente ha già pagato e va rimborsato | Nota di credito |

In Italia, se la fattura è già passata da SdI la rettifica **deve** essere una
nota di credito: quel documento è già stato acquisito e non si corregge a
posteriori.

## Cosa controlla il pacchetto

`validate()` sulle rettifiche non aggiunge vincoli propri: una nota di credito
strutturalmente valida è una fattura strutturalmente valida. I due problemi
tipici sono **rilievi** di `check()`, perché entrambi producono documenti che gli
enti accettano ma che a valle non funzionano:

| Codice | Quando |
|---|---|
| `correction_sign` | Nota di credito o di debito con **totale negativo** |
| `correction_no_reference` | Rettifica **senza** un `DocumentReference(kind="invoice")` |

```bash
einvoice check nota.json          # li stampa
einvoice check nota.json --strict # esce 1 se ce n'è almeno uno
einvoice inspect ricevuta.xml     # li mostra anche sui documenti in arrivo
```

## Riferimento rapido

```python
from einvoice import DocumentType

DocumentType.CREDIT_NOTE.is_credit_note              # True   (TD04)
DocumentType.SIMPLIFIED_CREDIT_NOTE.is_credit_note   # True   (TD08)
DocumentType.DEBIT_NOTE.is_debit_note                # True   (TD05)
DocumentType.SIMPLIFIED_DEBIT_NOTE.is_debit_note     # True   (TD09)
DocumentType.CREDIT_NOTE.corrects_an_earlier_document  # True
DocumentType.INVOICE.corrects_an_earlier_document      # False
DocumentType.SIMPLIFIED_CREDIT_NOTE.uncl1001         # "381"
```
