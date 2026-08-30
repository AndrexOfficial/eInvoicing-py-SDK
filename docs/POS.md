# Punto cassa: RT, reparti, POS

Un registratore telematico e una fattura elettronica descrivono **la stessa
vendita** in due vocabolari che non si somigliano. L'RT ragiona per reparti IVA
e indici di pagamento; la FatturaPA per aliquote, `Natura` e codici
`ModalitaPagamento`. Nessuno dei due sa dell'altro, e fino alla 0.7.0 il
pacchetto copriva solo il secondo.

Il costo di quel buco si è visto in due posti precisi, entrambi in un prodotto
reale e su documenti **fiscalmente validi**.

## 1. La fattura diceva sempre «bonifico»

`ModalitaPagamento` è obbligatorio. Non avendo una tabella da consultare, il
codice metteva `MP05` su ogni fattura — comprese quelle di un conto pagato in
contanti al banco. Il documento passa SdI e dice una cosa falsa su come sono
arrivati i soldi.

```python
from einvoice.pos import PosPaymentMethod, payment_means_for

payment_means_for(PosPaymentMethod.CASH).code    # PaymentMeans.CASH (MP01)
payment_means_for(PosPaymentMethod.CARD).code    # PaymentMeans.CARD (MP08)
```

### Il campo che conta è `exact`

La lista MP01–MP23 è stata scritta per la fatturazione, non per la cassa. Per
un paio di modi di pagare molto comuni al banco **non esiste un codice
dedicato**:

```python
voucher = payment_means_for(PosPaymentMethod.MEAL_VOUCHER)
voucher.code    # PaymentMeans.CARD — il meno sbagliato
voucher.exact   # False
voucher.note    # ...e perché
```

Restituire lo stesso oggetto nei due casi renderebbe indistinguibile «questo è
il codice giusto» da «questo è il meno sbagliato», che è esattamente la
differenza che un commercialista vorrebbe sapere.

`code = None` non è un buco: significa **non emettere il blocco
DatiPagamento**. Una fattura non incassata non ha una modalità da dichiarare, e
inventarne una la farebbe risultare pagata. Vale anche per un conto pagato
metà in contanti e metà con la carta: non ha *un* metodo, e sceglierne uno
sarebbe stampare una supposizione su un documento fiscale.

## 2. La fattura non citava il documento commerciale

Quando la vendita è già stata battuta sull'RT, il corrispettivo è già stato
trasmesso. La fattura emessa dopo descrive **la stessa** vendita: senza un
riferimento che le colleghi, lo stesso incasso risulta due volte e lo scorporo
non ha su cosa appoggiarsi.

```python
from einvoice.pos import ReceiptReference, link_receipt, check_pos_alignment

dc = ReceiptReference(number="0002-0041", date=date(2026, 8, 27),
                      rt_serial="99MEY012345")
link_receipt(invoice, dc)          # accoda la citazione alla causale
check_pos_alignment(invoice, dc)   # [] — collegata
```

FatturaPA non ha un blocco dedicato: i `DatiFattureCollegate` collegano
*fatture*. La prassi è citarlo in `Causale`, che è testo libero ripetibile e
sopravvive al giro di andata e ritorno. Il pacchetto **produce la stringa e si
ferma lì**: dove metterla lo decide il prodotto, che è l'unico a sapere se
quella causale è già occupata. `link_receipt` accoda e non sostituisce, perché
la descrizione della prestazione e il riferimento al corrispettivo servono
entrambe.

Non tocca gli importi: lo scorporo si fa nella chiusura di cassa, non dentro
la fattura.

## 3. I reparti IVA

Il reparto è l'unica cosa che l'RT sa di un articolo: non conosce le categorie
merceologiche, conosce «reparto 3». Se due reparti dichiarano la stessa
aliquota, o se una riga di fattura usa un'aliquota che nessun reparto copre, lo
scontrino e la fattura della stessa vendita smettono di quadrare — e se ne
accorge il commercialista, mesi dopo.

```python
from einvoice.pos import DepartmentTable, VatDepartment

table = DepartmentTable([VatDepartment(1, "10"), VatDepartment(2, "22")])
table.for_rate("22").index      # 2
table.for_rate("4")             # None — non battibile così com'è configurata
table.check(invoice)            # rilievi: aliquote ambigue, reparti duplicati…
```

`for_rate` risponde `None` invece di ripiegare su un reparto qualunque:
battere la vendita nel posto sbagliato è peggio che dire che non è battibile,
perché il totale per reparto smette di riconciliarsi e nessuno se ne accorge
fino alla chiusura.

## Cosa **non** c'è qui

Nessun protocollo di stampante. I driver Epson ePOS-Print, Custom, la coda di
stampa e la chiusura di cassa restano nel prodotto, che è l'unico a sapere
quale hardware ha in sala. Qui c'è solo ciò che è vero indipendentemente dal
modello: la traduzione fra i due vocabolari, e le verifiche che dicono quando i
due documenti stanno raccontando storie diverse.

## Il documento commerciale, e il centesimo che non torna

`einvoice.receipt` compone lo scontrino: righe, riepilogo IVA, pagamenti,
resto, lotteria.

```python
from einvoice.receipt import CommercialDocument, receipt_lines, check_receipt

doc = CommercialDocument(number="0002-0041", date=date.today(),
                         lines=[...], country="DE")
print("\n".join(receipt_lines(doc, width=42)))
```

**Una cassa e una fattura arrotondano in versi opposti**, ed è la cosa che il
modulo esiste per rendere esplicita. Il banco vende a prezzi *lordi*: il totale
è quello che il cliente paga e l'IVA si ricava per **scorporo** dal
corrispettivo di ogni aliquota. Una fattura si costruisce dal netto in su, riga
per riga, e ogni riga si arrotonda per conto suo.

Sulla stessa vendita — 2 coperti a 2,00 €, 2 primi a 12,00 € al 10 %, un vino a
18,00 € al 22 % — lo scontrino fa **46,00** e la fattura **46,01**. Nessuno dei
due sbaglia. Quel centesimo è quello che non torna alla chiusura quando lo
stesso incasso compare nei corrispettivi *e* in fattura, e
`check_receipt` lo misura invece di lasciarlo scoprire mesi dopo:

```
receipt_invoice_total_drift — La fattura per queste stesse righe totalizzerebbe
46.01 invece di 46.00 (+0.01): la cassa scorpora dal lordo, la fattura somma i
netti di riga arrotondati.
```

Gli altri rilievi: incassato meno del dovuto, codice lotteria malformato,
**codice lotteria su un incasso non interamente elettronico** (la lotteria
degli scontrini vuole il cashless, e stamparlo su un pagamento in contanti
promette al cliente una partecipazione che non ci sarà), documento dichiarato
fiscale senza matricola del dispositivo.

`fiscal` è `False` di default, e lo scontrino lo dice in testa: un documento
commerciale valido esce da un dispositivo omologato, quello che si stampa da
una termica è una copia di cortesia. Il valore predefinito non deve essere
quello che espone a una sanzione.

### La lingua è quella del paese di fatturazione

Chi compra al banco legge la lingua del posto, non quella di chi ha scritto il
software.

```python
CommercialDocument(..., country="DE")            # GESAMT, Nettobetrag, MwSt.
CommercialDocument(..., country="IT", locale="de")   # un negozio di Bolzano
```

Anche i metodi di pagamento: arrivavano sullo scontrino come `card` e
`meal_voucher`, cioè chiavi di programma finite in mano a un cliente. Ora sono
parole, nelle stesse 31 lingue del resto del pacchetto.

### Stampare

```python
from escpos.printer import Network
from einvoice.receipt import print_receipt

print_receipt(doc, Network("192.168.1.50"), open_drawer=True)
```

`print_receipt` accetta **qualunque** oggetto con l'interfaccia di
[python-escpos](https://python-escpos.readthedocs.io) — `Network`, `Usb`,
`Serial`, o il loro `Dummy()` che raccoglie i byte in memoria — e non lo
importa: è duck typing, quindi il pacchetto resta senza dipendenze.

Reimplementare ESC/POS a byte qui dentro sarebbe stato l'errore facile. Il
punto duro di quel protocollo non sono i codici di controllo: sono le **code
page**. Uno scontrino italiano è pieno di `à è ì ò ù` e di `€`, ogni modello li
vuole in una tabella diversa, e python-escpos ha un meccanismo apposta che ci
ha messo anni a diventare affidabile. Rifarlo male significa mojibake su un
documento fiscale.

Il cassetto si apre **dopo** il taglio e solo su richiesta: uno che scatta a
ogni preconto è uno che resta aperto.

## Il PDF, per chi lo legge

L'XML è il documento fiscale; il PDF è la copia che si allega a una mail e si
ritrova in archivio tre anni dopo.

```python
from einvoice.pdf import invoice_pdf, receipt_pdf, PdfBranding

open("fattura.pdf", "wb").write(invoice_pdf(inv, logo="logo.png"))
open("scontrino.pdf", "wb").write(receipt_pdf(doc, logo=logo_bytes))
```

```bash
einvoice pdf fattura.json -o fattura.pdf --logo logo.png --lang de
```

- **Restituiscono byte.** Un modulo che scrive file da sé va riscritto la prima
  volta che il file deve finire su un bucket.
- **Il logo** arriva come percorso *o* come byte: chi lo tiene su disco e chi lo
  tiene su un bucket non scrive codice diverso. Un logo illeggibile **non ferma
  il documento** — una fattura che non esce perché il PNG è corrotto è un danno
  peggiore di una fattura senza marchio. Vale sia per un file che non è
  un'immagine sia, cosa meno ovvia, per un PNG con l'intestazione giusta e il
  flusso dati rotto: quello si costruisce e fallisce **al disegno**, a documento
  già iniziato.
- **I numeri non si ricalcolano**: vengono da `vat_summary()`, gli stessi che
  finiscono nell'XML. Un PDF che dice una cifra e un XML che ne dice un'altra
  sulla stessa vendita è il difetto da non introdurre.
- **Lo scontrino PDF usa le stesse righe della termica**, non un secondo
  layout: comporne uno qui sarebbe il modo più veloce per farli divergere. La
  pagina è larga come il rotolo e alta quanto serve.
- **ReportLab è l'extra `[pdf]`**, come `cryptography` per la firma. Se manca,
  `PdfUnavailable` dice che è un problema di deploy e non un dato rotto: chi la
  cattura risponde «PDF non disponibile» e continua a emettere l'XML, che è la
  parte fiscale.

## Il ferro, per nome

La domanda dopo «mi serve un registratore?» è «quale posso comprare». Senza una
risposta, ognuno se la ricostruisce leggendo i listini — con l'esito prevedibile
che due prodotti della stessa casa finiscono per credere cose diverse sullo
stesso modello.

```bash
einvoice devices --models        # tutte le famiglie
einvoice devices --models IT     # solo quelle omologate in Italia
einvoice pos --terminals --country IT
```

```python
from einvoice.devices import devices_for_country, terminals_for_country
from einvoice.reference import fiscal_device_catalogue, pos_terminal_catalogue
```

**Questo pacchetto non parla con nessuna stampante e con nessun terminale**, e
non lo farà: il trasporto verso il ferro è locale, dipende dalla rete della
sala, e va tenuto nel prodotto. Qui c'è l'anagrafica — chi produce cosa, che
protocollo parla, come si collega, dove sta la documentazione — perché quella è
la parte che non cambia da un prodotto all'altro. Nessuna voce dichiara di
essere implementata: sarebbe una promessa che il pacchetto non può mantenere, e
chi lo incorpora la leggerebbe come propria.

### Dispositivi fiscali

`protocol` nomina il protocollo **come lo chiama il fornitore**;
`public_protocol` dice se la specifica è pubblica o se serve l'SDK del
produttore. L'omologazione è nazionale: `devices_for_country` non offre un RT
italiano a un negozio tedesco.

| Chiave | Produttore | Modelli | Protocollo | Collegamento | Mercati |
|---|---|---|---|---|---|
| `epson_rt` | Epson | FP-81II, FP-90III | ePOS-Print Fiscal XML (`/cgi-bin/fpmate.cgi`) — **pubblico** | LAN, USB, seriale | IT |
| `custom_rt` | Custom S.p.A. | Q3X, KUBE II | XML fiscale Custom (SDK Custom4Innovation), TCP 9100 | LAN, USB | IT |
| `rch_rt` | RCH | Print!F, ONDA, ABC | protocollo RCH (SDK del produttore) | LAN, seriale, USB | IT |
| `ditron_rt` | Ditron | Quadra, Labo | protocollo Ditron (SDK) | LAN, seriale | IT |
| `olivetti_rt` | Olivetti | Nettuna, Form 100 | protocollo Olivetti (SDK) | LAN, seriale, USB | IT |
| `swissbit_tse` | Swissbit | TSE microSD, TSE USB | modulo TSE hardware | USB | DE |
| `fiskaly_tse` | fiskaly | TSE cloud | REST — **pubblico** | cloud | DE, AT |
| `escpos_generic` | Epson, Star, Citizen, Bixolon | TM-T20III, TM-T88VII, TM-m30III, TSP143III, CT-S310II, SRP-330II | ESC/POS (TCP 9100) — **pubblico** | LAN, USB, Bluetooth | EU |

**`escpos_generic` non è un dispositivo fiscale.** Stampa comande, preconti e
copie di cortesia; da lì un documento commerciale valido non esce. È a catalogo
perché in sala c'è comunque, e perché scambiarla per un RT è l'errore che costa
una sanzione — c'è un test che le impedisce di dichiarare `receipt` fra le sue
capacità.

Le due TSE tedesche non stampano: **firmano**. Lo scontrino lo stampa una
termica qualunque, ed è per questo che compaiono senza capacità di stampa.

### Terminali di pagamento

`integration` dice *dove gira il codice*, che è la scelta che determina tutto il
resto: `cloud_api` (il server chiede, il terminale esegue), `terminal_api`
(protocollo diretto sul terminale, spesso in LAN, sopravvive a una linea che
cade), `device_sdk` (la app gira **sul** terminale Android), `softpos` (il
telefono è il terminale), `wallet` (QR, nessun ferro).

| Chiave | Fornitore | Modelli | Integrazione | Mercati |
|---|---|---|---|---|
| `stripe_terminal` | Stripe | BBPOS WisePOS E, Reader S700, Reader M2 | `cloud_api` | EU, GB, US |
| `sumup` | SumUp | Air, Solo, Solo Lite | `cloud_api` | EU, GB |
| `nexi` | Nexi | SmartPOS (PAX A920), SoftPOS | `device_sdk` | IT |
| `adyen` | Adyen | P400, V400m, S1E2L | `terminal_api` | EU, GB, US |
| `worldline` | Worldline (ex Ingenico, ex SIX) | YOMANI, YOXIMO, Move/5000, Desk/5000, VALINA | `terminal_api` | EU, CH |
| `pax` | PAX Technology | A920, A80, IM30 | `device_sdk` | EU, global |
| `verifone` | Verifone | V240m, P400, T650 | `device_sdk` | EU, global |
| `zettle` | Zettle (PayPal) | Reader 2, Terminal | `device_sdk` | EU, GB |
| `satispay` | Satispay | QR / app | `wallet` | IT, EU |

PAX è il ferro sotto molti SmartPOS di marca: l'acquirer cambia, l'hardware no.
Satispay non è un terminale ma un portafoglio — nessun ferro da comprare e
nessun collegamento all'RT da cablare, il che non lo esonera dal tracciamento
dell'incasso.

### Il collegamento POS ↔ registratore

In Italia è obbligatorio **dal 1° gennaio 2026**, in Grecia lo è già. Quali
firmware lo supportino cambia da modello a modello e da mese a mese, quindi il
catalogo **non lo dichiara per terminale**: sarebbe il campo che invecchia per
primo e su cui qualcuno prenderebbe una decisione d'acquisto. La domanda
«questo modello è già collegabile?» va fatta al fornitore; quella «il mio paese
lo pretende?» ha una risposta qui:

```python
device_regime("IT").pos_link_required   # True
device_regime("IT").pos_link_since      # date(2026, 1, 1)
```

## Regimi di cassa per paese

L'altra metà della domanda. Il pacchetto sapeva rispondere a «come si trasmette
una fattura in Portogallo» e non a «mi serve un registratore per vendere al
banco a Lisbona» — e sono regimi **distinti**: la Germania non ha fatturazione
elettronica B2C obbligatoria ma pretende una TSE su ogni cassa.

```bash
einvoice devices            # tutti i paesi profilati
einvoice devices IT         # dettaglio in JSON
einvoice pos                # incassi → ModalitaPagamento
```

```python
from einvoice.devices import device_regime

device_regime("IT").device_name        # 'Registratore Telematico (RT)'
device_regime("IT").pos_link_required  # True, dal 1° gennaio 2026
device_regime("CZ").requirement        # 'none' — EET abolita nel 2023
```

| `requirement` | Significa |
|---|---|
| `device` | Dispositivo fiscale omologato obbligatorio |
| `sector` | Solo in alcuni settori o sopra soglia (BE horeca, DK) |
| `software` | Nessun dispositivo, ma software certificato/attestato (FR, ES, PT) |
| `none` | Nessun obbligo |
| `unknown` | Non coperto da questa tabella |

`country_reference()` porta il regime sotto `fiscal_device`, quindi le
schermate che già mostrano le regole del paese rispondono anche a questa
domanda senza un secondo endpoint.

**Sui dati**: come per gli obblighi di fatturazione, sono orientamento
operativo e non consulenza fiscale, sono datati da
`FISCAL_DEVICES_VERIFIED_AS_OF`, e un paese non verificato dichiara `unknown`
invece di una risposta plausibile. Un test gli impedisce anche di portare
fatti a fianco: un dato accanto a un'ammissione di ignoranza si legge come un
dato.
