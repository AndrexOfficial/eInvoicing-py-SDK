# Scegliere il ferro: pro e contro

Questo documento è **giudizio**, non dato. I fatti — chi produce cosa, che
protocollo parla, per che via si raggiunge — stanno in `einvoice.devices` e si
interrogano da codice; qui c'è cosa ne penso, che è una cosa diversa e invecchia
in modo diverso.

Per questo non esiste un campo `recommended` nel catalogo: un booleano
«consigliato» dentro una struttura dati è un'opinione travestita da fatto, e
nessuno la aggiorna. Un documento datato dice almeno quando è stato scritto.

> Aggiornato al **31 agosto 2026**. Nessun prezzo: cambiano più in fretta di
> questo file, e una cifra vecchia è peggio di nessuna cifra.

```bash
einvoice pos --integrable --country IT    # i fatti dietro a tutto questo
einvoice devices --models IT
```

---

## Terminali di pagamento

### Stripe Terminal — la scelta di default se si integra

**Pro.** Server-driven puro: il backend crea l'intento, il lettore esegue, e non
c'è nessun SDK da installare in sala. La documentazione è pubblica e completa, il
set di operazioni è tutto (avvio, annullo, storno, stato) e l'esito torna via
**webhook**. C'è una sandbox vera in cui si sbaglia senza conseguenze. Il WisePOS
E sta in rete e non ha bisogno di un telefono accanto.

**Contro.** Le commissioni non sono le più basse per chi incassa poco. Il lettore
parla col cloud Stripe: se cade la linea, cade l'incasso — non c'è modalità
locale. E si è legati al loro hardware.

**Quando.** Quando il software deve avviare il pagamento e si vuole scrivere
codice una volta sola. È la via più corta da zero a un incasso funzionante.

### SumUp Solo — il rapporto costo/integrazione migliore per i piccoli

**Pro.** La Cloud API avvia il pagamento sul lettore da qualunque piattaforma
capace di fare HTTPS, senza vincolo di distanza fra cassa e lettore, e l'esito
torna via webhook. Costo d'ingresso basso, diffusissimo fra piccoli esercenti,
onboarding in giornata.

**Contro.** Server-driven **solo con Solo**: l'Air ha bisogno di un telefono che
faccia da ponte, e chi compra l'Air pensando di comandarlo dal gestionale scopre
tardi di aver comprato il modello sbagliato. Il set di operazioni documentato è
più stretto di quello di Stripe o Adyen.

**Quando.** Bar, chioschi, ambulanti, chi ha un volume che non giustifica un
contratto enterprise ma vuole comunque che la cassa comandi il POS.

### Adyen — l'unico che sopravvive alla linea che cade

**Pro.** La Terminal API funziona **in locale** oltre che via cloud: il terminale
e la cassa si parlano sulla LAN, e un'interruzione di internet non ferma il
servizio in sala. È la differenza che si sente il venerdì sera. Set completo,
webhook, hardware serio.

**Contro.** Onboarding enterprise: contratto, volumi, tempi. Per un locale
singolo è più macchina di quanta ne serva, e la complessità si paga in giornate
di integrazione.

**Quando.** Catene, volumi alti, o qualunque posto dove «la linea è saltata, non
possiamo incassare» sia una frase inaccettabile.

### Nexi — quello che il commercialista e la banca già conoscono

**Pro.** Il più diffuso in Italia, con le banche italiane dietro. Lo SmartPOS è
un Android su cui gira la propria applicazione, e le Payment Bridge API lo
raggiungono da remoto: due vie, entrambe reali.

**Contro.** Proprio le due vie sono il problema — vanno scelte prima di scrivere
una riga, e la documentazione è sparsa fra portali diversi. L'app on-device passa
da un marketplace, quindi c'è un processo di pubblicazione. E **XPay non
c'entra**: è il gateway e-commerce, ma il nome ricorre e fa perdere pomeriggi.

**Quando.** Quando il cliente ha già Nexi e cambiarlo non è sul tavolo — che in
Italia è spesso.

### Worldline — copertura europea, a patto di sapere cosa si ha in mano

**Pro.** Presenza enorme in Europa, una famiglia di terminali per ogni caso
d'uso, e la via svizzera (VALINA via Saferpay) che gli altri non hanno.

**Contro.** Più vie di integrazione con nomi simili, ereditate da fusioni
successive (Ingenico, SIX). Prima di scrivere codice bisogna stabilire **quale**
terminale e **quale** contratto: è la parte che fa perdere più tempo, e succede
prima di aver scritto niente.

**Quando.** Multi-paese europeo, o Svizzera.

### Satispay — ottimo, ma non è un POS

**Pro.** Nessun hardware da comprare, commissioni piatte e basse, diffusione
reale in Italia, API pulita e webhook. Per un piccolo esercente è la via meno
costosa in assoluto.

**Contro.** **Non è una carta**: copre solo i clienti che hanno l'app, quindi non
sostituisce un terminale, lo affianca. E c'è una trappola: il callback dice
soltanto che lo stato è *cambiato*, non qual è — chi lo tratta come conferma di
incasso registra un pagamento che potrebbe essere stato annullato.

**Quando.** Come secondo metodo, sempre. Come unico, mai.

### PAX, Verifone, Zettle — casi particolari

**PAX** è il ferro sotto molti SmartPOS di marca: l'acquirer cambia, l'hardware
no. Si integra scrivendo una app Android che gira sul terminale, e l'SDK arriva
con un accordo. **Verifone** simile, con documentazione pubblica migliore.
**Zettle** è la via PayPal: reader Bluetooth, SDK mobile, ottimo se la cassa è
già un telefono e pessimo se è un server.

Comune a tutti e tre: la logica gira **sul** terminale, quindi il gestionale non
lo comanda — lo ospita. È una scelta di architettura, non un dettaglio.

### Flatpay — buon prodotto, integrazione impossibile

**Pro.** Prezzo piatto e trasparente, installazione in un pomeriggio, pensato per
chi non vuole sentir parlare di integrazioni. Per un esercente che usa la loro
cassa e basta, è una scelta ragionevole.

**Contro.** **Sistema chiuso**: nessuna API del terminale, nessun SDK, nessun
portale sviluppatori. La «POS integration» che pubblicizzano è la loro cassa col
loro terminale. Se il gestionale deve avviare l'incasso, Flatpay è fuori — non
«difficile», fuori.

**Quando.** Mai, se si sta leggendo questo file.

---

## Stampanti fiscali (RT)

### Epson FP-81II / FP-90III — il default, e per una ragione precisa

**Pro.** È l'**unico** con la specifica pubblicata per intero (ePOS-Print
Fiscal), quindi si integra leggendo invece che telefonando. Rete nativa, set
completo — documento commerciale, reso, annullo, chiusura Z, cassetto, codice
lotteria — ed è il più diffuso in Italia, il che significa che qualunque tecnico
lo conosce e i ricambi si trovano.

**Contro.** Costa più delle alternative. L'estensione fiscale va abilitata e il
certificato RT lo installa un tecnico abilitato: non è una macchina che si mette
in funzione da soli.

**Quando.** Sempre, salvo ragioni specifiche in contrario. È l'unica su cui si
può stimare il lavoro di integrazione prima di iniziarlo.

### Custom Q3X / KUBE II — l'alternativa italiana

**Pro.** Produttore italiano, assistenza vicina, formati compatti che stanno dove
un'Epson non entra.

**Contro.** Il protocollo arriva con l'SDK del produttore, non è pubblico. Il
firmware va portato in emulazione **XML** e fuori da quella modalità la stessa
porta 9100 risponde con un protocollo diverso — un dettaglio che costa mezza
giornata a chi non lo sa. Meno operazioni implementate nei driver esistenti
(niente reso, niente lotteria).

**Quando.** Quando lo spazio o l'assistenza locale contano più della velocità di
integrazione.

### RCH, Ditron, Olivetti — solo se ci sono già

**Pro.** Diffuse in nicchie precise (RCH nella panificazione e nel fast food),
prezzi competitivi, prodotti solidi.

**Contro.** Protocollo dietro SDK del produttore, e nessun driver pronto. Vuol
dire partire da zero, con una specifica da richiedere.

**Quando.** Quando il cliente le ha già e sostituirle non è sul tavolo. Non come
scelta iniziale, a meno di volumi che giustifichino il lavoro.

### Termiche ESC/POS — indispensabili, e non fiscali

**Pro.** Costano poco, lo standard è vero e pubblico, funzionano ovunque e sono
il ferro che in sala c'è comunque: comande in cucina, preconti, copie di
cortesia.

**Contro.** **Non emettono un documento commerciale valido.** Scambiarle per un
RT è l'errore che costa una sanzione, ed è facile da fare perché stampano lo
stesso pezzo di carta.

**Quando.** In cucina e per i preconti, sempre. Alla cassa come sostituto di un
RT, mai.

---

## Cassetti portavalori

Non c'è una scelta da fare, e vale la pena dirlo perché ci si perde tempo:
**qualunque cassetto con porta DK (RJ11/RJ12) va bene** — APG, Star, Safescan,
Virtuos, Custom. Il pin standard è il 2, alcuni cablano il 5, sparare entrambi è
innocuo.

**Non si integra il cassetto: si integra la stampante che lo apre.** Un cassetto
a impulso è una serratura che scatta quando arrivano 24 V; non ha indirizzo, non
ha protocollo, non risponde, e lo stato «aperto» non torna indietro da nessuna
parte. Cercarne il driver è il vicolo cieco più comune al banco.

L'unica cosa su cui scegliere è la robustezza meccanica, che si valuta aprendolo
e chiudendolo in negozio.

---

## Abbinamenti

Senza prezzi, e senza fingere che ci sia una risposta sola.

| Situazione | Terminale | Fiscale | Perché |
|---|---|---|---|
| Bar o piccolo locale in Italia, si vuole integrare | SumUp Solo, o Nexi se c'è già | Epson FP-81II | La Cloud API costa poco e basta; l'Epson è l'unica su cui stimare il lavoro |
| Ristorante che apre da zero | Stripe WisePOS E | Epson FP-90III | Doc pubblica da entrambe le parti: nessuna telefonata prima di partire |
| Catena, più sedi | Adyen | Epson FP-90III per sede | La Terminal API locale regge quando salta la linea |
| Palestra, incassi al banco | Stripe Terminal | dipende dal regime del paese | Server-driven: il gestionale comanda, l'operatore non tocca il POS |
| Ambulante, mercato | SumUp Solo | secondo il regime | Nessuna infrastruttura, 4G, si accende e incassa |
| Svizzera | Worldline VALINA | nessun obbligo di RT | La via Saferpay è quella che copre il mercato |
| Germania | Stripe o Adyen | TSE (Swissbit se c'è un PC, fiskaly se è un tablet) | La TSE firma, la stampa la fa una termica qualunque |

E in tutti i casi: **Satispay come secondo metodo**, perché non costa hardware e
in Italia una parte dei clienti lo cerca.

---

## Le due domande da fare prima di comprare

1. **Il software deve avviare l'incasso?** Se sì, il campo da guardare è
   `start_payment`, e sistemi come Flatpay escono dall'elenco prima ancora di
   parlare di prezzo. Se no, quasi tutto va bene e si sceglie sulle commissioni.
2. **Cosa succede quando salta la linea?** Un terminale cloud smette di
   incassare; uno con protocollo locale no. È una domanda che si fa una volta e
   che determina l'infrastruttura per anni — vedi la differenza fra i canali
   `lan` e `api` in [POS.md](POS.md#per-che-via-ci-si-parla).
