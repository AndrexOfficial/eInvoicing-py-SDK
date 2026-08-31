# Leggere una fattura ricevuta

Il pacchetto genera FatturaPA, UBL e CII — e li **rilegge** tutti e tre. È la
metà dell'integrazione che manca più spesso, ed è ormai la metà obbligatoria: la
Germania impone di **accettare** fatture strutturate dal 2025-01-01, la Francia
da tutti nel 2026, l'Italia da anni. Non si è conformi solo emettendo.

```python
from einvoice import parse_invoice, detect_standard

detect_standard(xml)       # 'fatturapa' | 'ubl' | 'cii'
invoice = parse_invoice(xml)
```

```bash
einvoice inspect ricevuta.xml     # chi, quanto, e se torna
einvoice parse   ricevuta.xml     # → JSON
```

## Il riconoscimento è per namespace, non per contenuto

L'elemento radice è l'unica cosa su cui tutti questi standard sono espliciti:

| Radice | Formato |
|---|---|
| `rsm:CrossIndustryInvoice` | `cii` |
| `Invoice` / `CreditNote` (namespace UBL) | `ubl` |
| `p:FatturaElettronica` | `fatturapa` |

Niente euristiche sul contenuto: un documento non riconosciuto solleva un errore
che dice cosa si aspettava, invece di essere interpretato a caso.

`parse_invoice(xml, standard="ubl")` forza il parser quando la radice mente
(capita con intermediari che rinamespaceano i documenti).

## I totali si ricalcolano, non si credono

Questa è la scelta di progetto più importante del modulo.

Un documento ricevuto **dichiara** i propri totali. Qui si estraggono le
**righe** e si lascia che sia `Invoice` a derivare gli importi, con lo stesso
codice che usa per una fattura in uscita. Il totale che leggi da un invoice
parsato è quindi *quello che le righe del fornitore producono*, non quello che
il fornitore afferma.

Perché: importare il totale dichiarato come fatto nasconde esattamente il caso
che vuoi vedere — quello in cui non coincide.

```python
from einvoice import compare_declared_totals

r = compare_declared_totals(xml)
r["declared"]     # 9999.00  ← quello che dice il documento
r["computed"]     # 1220.00  ← quello che producono le sue righe
r["difference"]   # 8779.00  ← da chiarire prima di pagare
```

`einvoice inspect` esce con codice **1** quando i due divergono: è l'unica
discrepanza per cui vale la pena fermare una pipeline.

`declared` è `None` quando il documento non dichiara un totale — succede con i
profili Factur-X header-only.

## Cosa sopravvive al viaggio

Tutto ciò che **EN 16931 modella**: numero, data, valuta, tipo documento, le due
parti con indirizzo e identificativi fiscali, le righe con quantità, prezzo,
aliquota, unità di misura, codice articolo e periodo di competenza, gli sconti di
riga e di documento, i mezzi di pagamento con IBAN e scadenza, i riferimenti
(ordine, contratto, DDT, fatture collegate), gli allegati, le note.

### Cosa NON sopravvive, e da quale formato

| Dato | FatturaPA | UBL | CII |
|---|---|---|---|
| Bollo (`stamp_duty`) | ✅ elemento dedicato | ⚠️ torna come onere | ⚠️ torna come onere |
| Cassa previdenziale (`funds`) | ✅ | ⚠️ come onere | ⚠️ come onere |
| Ritenuta (`withholdings`) | ✅ | ❌ non modellata | ❌ non modellata |
| Art. 73 (`art73`) | ✅ | ❌ | ❌ |
| `Natura` con sotto-codice | ✅ `N6.3` | ⚠️ → `N6.9` | ⚠️ → `N6.9` |
| `CodiceDestinatario` / PEC | ✅ | ❌ | ❌ |
| Nome della banca (`bank_name`) | ✅ `IstitutoFinanziario` | ❌ vedi sotto | ✅ |
| Email di contatto | ✅ `Contatti` | ✅ BG-6/BG-9 | ✅ BT-43 |
| REA (`registration_number`) | ✅ | ✅ | ✅ |
| `article_code_type` | ✅ `CodiceTipo` | ❌ | ❌ |
| Tipo documento «semplificato» | ✅ `TD07/08/09` | ⚠️ → `TD01/04/05` | ⚠️ → `TD01/04/05` |
| Aliquota di uno sconto/onere **di documento** | ❌ vedi sotto | ✅ | ✅ |

**FatturaPA è lossless, con una sola eccezione.** C'è un test che confronta
*ogni* campo del modello dopo il giro e pretende zero differenze. Prima non lo
era affatto — ritenuta, cassa, sconti di documento e allegati venivano scritti
nell'XML e poi buttati via in lettura.

L'eccezione è **l'aliquota di uno sconto o onere di documento**:
`ScontoMaggiorazione` porta `Tipo`, `Percentuale` e `Importo`, e non ha un campo
per l'aliquota IVA a cui l'onere appartiene. Il documento emesso resta corretto e
coerente — i riepiloghi e `ImportoTotaleDocumento` ne tengono conto — ma in
lettura l'aliquota va assunta, e il modello assume quella della prima riga.
Ricavarla confrontando i riepiloghi con le righe funzionerebbe, e **non** viene
fatto di proposito: significherebbe ricostruire un valore a partire da totali
che questo modulo per principio ricalcola invece di credere.

Il **nome della banca** in UBL è l'unica omissione volontaria: Peppol BIS 3.0
ammette in `cac:FinancialInstitutionBranch` il solo `cbc:ID` (il BIC), e
aggiungere `cac:FinancialInstitution` per guadagnare un campo nel round-trip
significherebbe emettere un documento che Peppol può rifiutare. Meglio perdere
il nome che la validazione.

La riga della `Natura` merita una parola: EN 16931 ha **una** categoria
`AE` (reverse charge) dove l'Italia ne ha nove, quindi il sotto-codice non può
sopravvivere a un giro attraverso UBL o CII. Il parser restituisce il membro
generico della famiglia (`N6.9`) e conserva la motivazione testuale sulla riga.
È una perdita **dichiarata e testata**, non una sorpresa in produzione.

Lo stesso vale per il **tipo documento**: UNCL 1001 ha tre codici dove l'Italia
ne ha nove, quindi `TD08` (nota di credito semplificata) torna come `TD04`. Ciò
che sopravvive sempre è il **verso** — una nota di credito torna una nota di
credito, mai una fattura. Vedi [CORRECTIONS.md](CORRECTIONS.md).

Corollario pratico: se emetti verso SdI e ti serve un round-trip fedele, il
formato di riferimento è FatturaPA. Se ricevi da un fornitore estero, quello che
arriva è quello che EN 16931 sa dire, e va bene così.

## Prezzi quotati «per N unità»

Nel commercio all'ingrosso il prezzo si quota spesso per 100 o per 1000 pezzi, e
entrambe le sintassi lo esprimono affiancando all'importo una **quantità base**
(`cbc:BaseQuantity` in UBL, `ram:BasisQuantity` in CII).

Il modello non ha il concetto: `LineItem.unit_price` è il prezzo di **una**
unità. La normalizzazione avviene in lettura — l'importo viene diviso per la
base — così il totale di riga coincide con quello dichiarato dal mittente.

```
<cbc:PriceAmount>50.00</cbc:PriceAmount>
<cbc:BaseQuantity>10</cbc:BaseQuantity>   quantità 10  →  riga = 50.00, non 500.00
```

Leggere l'importo ignorando la base moltiplicava la riga per la base: un errore
di dieci volte su un documento perfettamente valido. In ri-emissione si scrive il
prezzo unitario per una unità: stessi soldi, scritti diversamente.

## Una fattura letta è una fattura usabile

Il risultato non è una struttura di sola lettura: è lo stesso `Invoice` che usi
per emettere.

```python
invoice = parse_invoice(received)
invoice.validate()                      # le regole del paese del cedente
invoice.check()                         # rilievi (IVA intra-UE, aliquote, date)
get_renderer("ubl").render(invoice)     # ricevi, archivia, inoltra
```

Il ciclo ricevi → analizza → inoltra è la forma di qualunque flusso di ciclo
passivo, ed è coperto dai test su tutti e 30 i paesi profilati e in entrambe le
sintassi EN 16931.

## Un file FatturaPA può contenere più fatture

FatturaPA prevede il **lotto**: un solo `FatturaElettronicaHeader` — stesso
cedente, stesso cessionario — seguito da più `FatturaElettronicaBody`, uno per
fattura. Non è un caso di scuola: è la forma normale delle forniture ricorrenti
e di molti flussi di ciclo passivo.

```python
from einvoice import parse_invoices

for invoice in parse_invoices(received):     # una qualunque delle due sintassi
    archivia(invoice)
```

`parse_invoices()` restituisce sempre una lista, per tutti i formati: uno solo
per UBL e CII, tutti quelli presenti per FatturaPA. È la funzione da usare
quando il file arriva da fuori e non sai cosa contiene.

`parse_invoice()` resta la forma singolare e su un lotto **solleva**, dicendo
quante fatture ha trovato:

```
FatturaPA: il file contiene 3 fatture (lotto). parse_invoice() ne restituisce
una sola: usa parse_invoices() per leggerle tutte.
```

Prima restituiva la prima e buttava via le altre senza dire niente, che sul
ciclo passivo significa fatture che non entrano in contabilità mentre tutto
sembra funzionare. Un avviso nei log non sarebbe bastato: chi non li legge
avrebbe continuato a perdere documenti. L'unica opzione che non nasconde nulla è
fermarsi.

## Lo sconto documento e l'aliquota che il formato non trasporta

`ScontoMaggiorazione` a livello di documento, nello schema FatturaPA, contiene
`Tipo`, `Percentuale` e `Importo` — **non** `AliquotaIVA`. A quale aliquota lo
sconto sia stato applicato, il file non lo dice in quel punto.

Conta, però. Su una fattura con più aliquote uno sconto di 5 € tolto
dall'esente o tolto dal 22% produce due riepiloghi diversi e due totali diversi:

```
sconto sull'esente : 22% → 93.60 | 0% → 45.00   totale 161.20
sconto sul 22%     : 22% → 88.60 | 0% → 50.00   totale 160.10
```

L'informazione c'è, solo altrove: i `DatiRiepilogo` dichiarano l'imponibile per
aliquota, e la **differenza fra quello e la somma delle righe è lo sconto**. Il
parser la legge da lì e rimette `vat_rate` al suo posto, così il giro
ricevi → inoltra riproduce il documento invece di riscriverlo.

L'attribuzione avviene **solo su corrispondenza esatta**, o quando un solo
bucket si è mosso. Nel dubbio `vat_rate` resta `None`: attribuire a caso
sarebbe lo stesso spostamento di imponibile, con l'aggravante di sembrare
intenzionale. Quel che resta non attribuito lo segnala
`compare_declared_totals`.

## Le ricevute SdI: leggere la risposta, non solo mandare la domanda

Il ciclo non finisce con la trasmissione. SdI risponde con file XML — consegna,
scarto, mancata consegna, esito del committente — che arrivano dal provider,
dalla PEC o dal portale, e che ogni integrazione finiva per riparsarsi da sola.

```python
from einvoice.notifications import parse_sdi_receipt

ricevuta = parse_sdi_receipt(xml)
ricevuta.kind          # 'NS'
ricevuta.type          # NotificationType.REJECTED
ricevuta.sdi_id        # per riconciliare con la trasmissione
ricevuta.errors        # [SdiError(code='00404', description='Fattura duplicata')]

lifecycle.apply(ricevuta.to_notification())
```

Su uno scarto il **codice d'errore è il dato più utile dell'intero flusso**:
dice perché la fattura è stata rifiutata, e senza si ricomincia a tentativi. Un
`00404` (duplicata) non va ritrasmesso, un `00311` (codice destinatario non
valido) va corretto e rimandato: sono due azioni opposte, e distinguerle
richiede il codice.

Sono riconosciute tutte e sette le sigle — `RC`, `NS`, `MC`, `NE`, `DT`, `AT`,
`EC` — e su `NE`/`EC` l'esito `EC01`/`EC02` diventa il campo `positive`.

**Il namespace non si pretende.** Alcuni intermediari lo riscrivono, altri lo
tolgono: si guarda il nome locale della radice, come già fa il lettore
FatturaPA e per lo stesso motivo. Pretenderlo farebbe fallire file
perfettamente validi.

**I campi opzionali restano opzionali.** Una ricevuta a cui manca un elemento
non è rotta: è di un tipo che quell'elemento non lo porta, o di un intermediario
che lo omette. Sollevare lì bloccherebbe la riconciliazione per un dato che
spesso non serve. Una radice non riconosciuta invece **solleva**, perché chi
passa un file qui si aspetta una ricevuta e proseguire su un documento diverso è
peggio che fermarsi.

## Limiti

- **Non si valida contro lo schema XSD.** Il parser legge quello che trova; un
  documento malformato dà `ValidationError` sul parsing XML, ma la conformità
  formale allo standard non viene verificata. Per quello serve il validatore
  ufficiale del formato.
- **Non si verifica la firma.** Un `.p7m` va scartato prima
  (`einvoice.signer` firma, non verifica).
- **I profili Factur-X header-only** (MINIMUM, BASIC WL) non contengono righe
  per definizione: un invoice letto da uno di quelli ha `lines == []` e un totale
  calcolato pari a zero. Il totale dichiarato resta leggibile con
  `compare_declared_totals`.
