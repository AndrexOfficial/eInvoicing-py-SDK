# Firma, certificati e conservazione

Firmare una fattura è la parte facile. La parte che si rompe è il
**certificato**: scade, e nel giorno in cui scade non succede niente di
visibile. Il file si apre come sempre, la firma viene prodotta come sempre, e
il documento viene rifiutato a valle — settimane dopo che qualcuno aveva
guardato la schermata di configurazione e l'aveva vista verde.

Questa pagina dice come firmare, e soprattutto cosa controllare prima.

---

## Firmare

```python
from einvoice import sign_cades, sign_filename

p7m = sign_cades(xml_bytes, p12_bytes, "passphrase")   # PKCS#7 attached, SHA-256
name = sign_filename("IT01234567890_00001.xml")        # → …xml.p7m
```

La firma è **attached**: l'XML viaggia dentro la busta, come SdI richiede per
i `.p7m`. `cryptography` è una dipendenza opzionale (`pip install
einvoice[signing]`) importata pigramente, così il core resta senza dipendenze.

Per l'engine c'è l'adattatore:

```python
from einvoice import EInvoiceEngine, P12Signer

engine = EInvoiceEngine(renderer, transport, signer=P12Signer("firma.p12", "pw"))
```

### Il limite dichiarato

`cryptography` produce CMS/PKCS#7 standard con gli attributi firmati
`contentType`, `messageDigest`, `signingTime` e SMIME-capabilities. **CAdES-BES
per ETSI EN 319 122-1 richiede in più l'attributo `signing-certificate-v2`
(ESS)**, che il builder non espone. In pratica il validatore SdI accetta le
firme PKCS#7 attached ben formate fatte con un certificato *qualificato*; per
la conformità ETSI garantita — e per la conservazione a norma — serve un
servizio di firma accreditato o un HSM, oppure si lascia ri-firmare al
conservatore.

Il certificato deve essere di **firma elettronica qualificata** (eIDAS)
intestato a chi firma. Un certificato TLS non ha alcun valore per SdI.

## Controllare il certificato prima di usarlo

```python
from einvoice import SigningUnavailable, inspect_p12

try:
    cert = inspect_p12(archivio, passphrase)
except SigningUnavailable:
    ...          # l'extra non è installato: qui non possiamo controllare
except ValueError:
    ...          # archivio non valido o passphrase sbagliata → rifiuta
```

`inspect_p12()` apre l'archivio e non firma niente. Quello che restituisce:

| Campo / metodo | Risponde a |
|---|---|
| `subject`, `issuer` | Di chi è, e chi l'ha emesso |
| `serial_number` | Quale certificato è, quando ce n'è più d'uno |
| `valid_from`, `valid_until` | Da quando e fino a quando |
| `is_expired(on=…)` | È già scaduto? |
| `is_not_yet_valid(on=…)` | È stato caricato in anticipo? |
| `days_until_expiry(on=…)` | Quanti giorni restano (negativo se scaduto) |
| `expires_within(30)` | Va rinnovato adesso? |

Le date sono lette in **UTC**: la validità di un certificato è UTC, e leggerla
in ora locale sposta il confine di un giorno.

### Due errori, non uno

| Eccezione | Significa | Cosa farne |
|---|---|---|
| `ValueError` | L'archivio o la passphrase sono sbagliati | **Rifiutare** la configurazione |
| `SigningUnavailable` | Manca `cryptography` su questa macchina | Accettare e ricontrollare alla prima firma |

La distinzione è il punto. Entrambe le piattaforme che incorporano il
pacchetto le avevano collassate in un `except Exception` che significava «manca
l'estensione», e quindi **un archivio corrotto veniva salvato come valido** —
per riemergere al primo invio reale.

`SigningUnavailable` eredita anche da `RuntimeError`, che è ciò che veniva
sollevato prima: chi già lo catturava non deve cambiare niente.

## Cosa mostrare a chi configura

Una schermata di setup che dice solo «certificato caricato ✓» sta nascondendo
l'unica informazione che conta. Il minimo utile:

- **il soggetto**, per riconoscere *quale* certificato è caricato;
- **la scadenza**, sempre, non solo quando è vicina;
- **un avviso a 30 giorni**, perché il rinnovo di una firma qualificata non è
  istantaneo;
- **il rifiuto in salvataggio** se il certificato è già scaduto: accettarlo
  significa produrre firme che verranno respinte.

## Conservazione

```python
from einvoice import build_conservation_package, WebhookConservationProvider

zip_bytes = build_conservation_package(documents)   # ZIP + manifest + pdd_index
```

Il pacchetto è quello da **consegnare a un conservatore accreditato**: non è
di per sé conservazione a norma. `WebhookConservationProvider` lo consegna a
un endpoint HTTP se il conservatore ne espone uno.

Quanto va conservato dipende dal paese, e la risposta sta nei profili:

```python
from einvoice import profile_for

profile_for("IT").fiscal_rules.retention_years   # 10
profile_for("DE").fiscal_rules.retention_years   # 10
profile_for("US").fiscal_rules.retention_years   # None — è regola statale
```

Vedi [TAXES.md](TAXES.md) per le altre regole non-aliquota e
[TRANSPORT.md](TRANSPORT.md) per i canali di invio.
