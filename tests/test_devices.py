"""Regimi di cassa per paese.

Il pacchetto sapeva rispondere a «come si trasmette una fattura in Portogallo»
e non a «mi serve un registratore di cassa per vendere al banco a Lisbona».
Quello che va sorvegliato qui non sono i singoli fatti — cambiano, e sono
datati apposta — ma le due proprietà che li rendono usabili: che ogni paese
profilato abbia una risposta, e che una risposta non verificata *si dichiari*
tale invece di somigliare a un dato.
"""
import json
from datetime import date, timedelta

import pytest

from einvoice import supported_countries
from einvoice.devices import (
    CONNECTIONS,
    DEVICE_CAPABILITIES,
    DEVICE_KINDS,
    FISCAL_DEVICE_MODELS,
    FISCAL_DEVICE_REGIMES,
    FISCAL_DEVICES_VERIFIED_AS_OF,
    INTEGRATION_CHANNELS,
    POS_TERMINALS,
    REPORTING_KINDS,
    REQUIREMENT_KINDS,
    TERMINAL_CAPABILITIES,
    by_channel,
    countries_requiring_a_device,
    device_regime,
    devices_for_country,
    devices_of_kind,
    drivable_devices,
    programmable_terminals,
)
from einvoice.reference import (
    all_device_references,
    country_reference,
    device_reference,
    fiscal_device_catalogue,
    integrable_devices,
    pos_terminal_catalogue,
)


def test_every_profiled_country_has_an_answer():
    """Un paese di cui dichiariamo aliquote e obblighi di fattura, e su cui poi
    la domanda «serve una cassa?» resta senza risposta, è coperto a metà."""
    assert set(supported_countries()) <= set(FISCAL_DEVICE_REGIMES)


@pytest.mark.parametrize("code", sorted(FISCAL_DEVICE_REGIMES))
def test_every_regime_uses_the_declared_vocabulary(code):
    regime = FISCAL_DEVICE_REGIMES[code]

    assert regime.requirement in REQUIREMENT_KINDS
    assert regime.reporting in REPORTING_KINDS
    assert regime.country == code


@pytest.mark.parametrize("code", sorted(FISCAL_DEVICE_REGIMES))
def test_a_country_with_a_device_names_it(code):
    """«Serve un dispositivo» senza dire quale non è un'informazione: è
    l'operatore che deve riconoscerlo nel listino del fornitore."""
    regime = FISCAL_DEVICE_REGIMES[code]
    if regime.needs_a_device:
        assert regime.device_name, code


@pytest.mark.parametrize("code", sorted(FISCAL_DEVICE_REGIMES))
def test_a_country_without_a_device_does_not_name_one(code):
    regime = FISCAL_DEVICE_REGIMES[code]
    if regime.requirement in ("none", "unknown"):
        assert not regime.device_name, code


@pytest.mark.parametrize("code", sorted(FISCAL_DEVICE_REGIMES))
def test_every_regime_explains_itself(code):
    """Vale soprattutto per i «none» e gli «unknown»: senza nota sono
    indistinguibili da una riga che nessuno ha compilato."""
    assert FISCAL_DEVICE_REGIMES[code].notes, code


@pytest.mark.parametrize("code", sorted(FISCAL_DEVICE_REGIMES))
def test_an_unknown_regime_claims_nothing_else(code):
    """La riga «non lo sappiamo» non deve portare fatti a fianco: un dato
    accanto a un'ammissione di ignoranza si legge come un dato."""
    regime = FISCAL_DEVICE_REGIMES[code]
    if regime.requirement == "unknown":
        assert regime.reporting == "unknown"
        assert not regime.device_name
        assert regime.certified_software is None
        assert regime.receipt_lottery is False
        assert regime.pos_link_required is False


@pytest.mark.parametrize("code", sorted(FISCAL_DEVICE_REGIMES))
def test_a_pos_link_obligation_carries_a_date_or_none(code):
    regime = FISCAL_DEVICE_REGIMES[code]
    if regime.pos_link_since is not None:
        assert regime.pos_link_required, code


def test_italy_is_the_case_the_products_actually_run():
    it = device_regime("IT")

    assert it.device_name.startswith("Registratore Telematico")
    assert it.reporting == "daily"
    assert it.receipt_lottery is True
    assert it.pos_link_required and it.pos_link_since == date(2026, 1, 1)


def test_an_abolished_regime_is_recorded_as_abolished():
    """La Repubblica Ceca ha abolito l'EET nel 2023. Lasciarla fra i paesi con
    obbligo manderebbe qualcuno a comprare un registratore che non serve."""
    cz = device_regime("CZ")

    assert cz.requirement == "none"
    assert "EET" in cz.notes


def test_an_unlisted_country_answers_unknown_instead_of_raising():
    """«Non lo sappiamo, chiedi» è una risposta utile in una schermata di
    configurazione; un KeyError non lo è."""
    assert device_regime("ZZ").requirement == "unknown"
    assert device_regime("").requirement == "unknown"


def test_countries_requiring_a_device_is_sorted_and_non_empty():
    codes = countries_requiring_a_device()

    assert codes == sorted(codes)
    assert "IT" in codes and "CZ" not in codes


def test_the_data_says_how_old_it_is():
    assert date.today() + timedelta(days=1) >= FISCAL_DEVICES_VERIFIED_AS_OF


# ── la vista JSON ─────────────────────────────────────────────────────


def test_the_country_reference_now_answers_both_halves_of_the_question():
    """Le stesse schermate che già mostrano le regole del paese ricevono il
    regime di cassa senza dover chiamare un secondo endpoint."""
    it = country_reference("IT")

    assert it["fiscal_device"]["needs_a_device"] is True
    assert it["fiscal_device"]["pos_link_required"] is True


def test_the_views_are_json_safe():
    json.dumps({"one": device_reference("IT"), "all": all_device_references(),
                "country": country_reference("PT")})


def test_the_device_view_carries_its_own_date():
    assert device_reference("DE")["verified_as_of"] == FISCAL_DEVICES_VERIFIED_AS_OF.isoformat()


# ── il catalogo del ferro ─────────────────────────────────────────────
#
# «Mi serve un registratore?» ha una risposta nel modulo sopra; «quale posso
# comprare» è la domanda dopo, e senza catalogo ognuno se la ricostruisce
# leggendo listini — con l'esito che due prodotti della stessa casa credono
# cose diverse sullo stesso modello.


@pytest.mark.parametrize("key", sorted(FISCAL_DEVICE_MODELS))
def test_every_device_declares_its_key_and_a_protocol(key):
    device = FISCAL_DEVICE_MODELS[key]

    assert device.key == key
    assert device.vendor and device.models and device.protocol
    assert set(device.connection) <= set(CONNECTIONS), device.connection
    assert set(device.capabilities) <= set(DEVICE_CAPABILITIES), device.capabilities


@pytest.mark.parametrize("key", sorted(FISCAL_DEVICE_MODELS))
def test_a_device_names_the_markets_where_it_is_type_approved(key):
    """L'omologazione è nazionale: un catalogo senza mercati manderebbe qualcuno
    a comprare un RT italiano per un negozio di Monaco."""
    device = FISCAL_DEVICE_MODELS[key]

    assert device.countries
    for code in device.countries:
        assert code == "EU" or (len(code) == 2 and code.isupper()), code


def test_the_escpos_family_is_marked_as_not_fiscal():
    """Scambiare una termica per un RT è l'errore che costa una sanzione, ed è
    facile da fare perché stampano lo stesso pezzo di carta."""
    escpos = FISCAL_DEVICE_MODELS["escpos_generic"]

    assert escpos.fiscal is False
    assert "receipt" not in escpos.capabilities, "non può emettere un documento commerciale"
    assert "NON è un dispositivo fiscale" in escpos.notes


@pytest.mark.parametrize("key", sorted(FISCAL_DEVICE_MODELS))
def test_a_fiscal_device_can_at_least_print_and_close_the_day(key):
    device = FISCAL_DEVICE_MODELS[key]
    # I moduli di sicurezza (TSE) non stampano: firmano. Non sono stampanti.
    if device.fiscal and device.capabilities:
        assert "receipt" in device.capabilities and "z_report" in device.capabilities, key


@pytest.mark.parametrize("key", sorted(FISCAL_DEVICE_MODELS))
def test_a_closed_protocol_says_where_to_get_it(key):
    """«Protocollo proprietario» senza dire a chi chiederlo è un vicolo cieco."""
    device = FISCAL_DEVICE_MODELS[key]
    if not device.public_protocol:
        assert device.docs_url or "SDK" in device.protocol or device.notes, key


@pytest.mark.parametrize("key", sorted(POS_TERMINALS))
def test_every_terminal_declares_a_known_integration_shape(key):
    terminal = POS_TERMINALS[key]

    assert terminal.key == key
    assert terminal.vendor and terminal.models and terminal.countries
    assert terminal.integration in {"cloud_api", "terminal_api", "device_sdk",
                                    "softpos", "wallet", "vendor_pos"}, terminal.integration
    assert set(terminal.connection) <= set(CONNECTIONS), terminal.connection


def test_italy_gets_its_own_devices_before_the_generic_ones():
    keys = [d.key for d in devices_for_country("IT")]

    assert keys[0] == "epson_rt"
    assert keys.index("escpos_generic") == len(keys) - 1, "la non-fiscale per ultima"
    assert "swissbit_tse" not in keys, "la TSE tedesca non serve a un negozio italiano"


def test_germany_does_not_get_offered_an_italian_rt():
    assert "epson_rt" not in [d.key for d in devices_for_country("DE")]
    assert "swissbit_tse" in [d.key for d in devices_for_country("DE")]


def test_an_unknown_country_still_gets_the_generic_hardware():
    """Una termica ESC/POS funziona ovunque: rispondere con una lista vuota
    farebbe sembrare che non ci sia niente da collegare."""
    keys = [d.key for d in devices_for_country("ZZ")]

    # La termica e il cassetto: nessuno dei due è legato a un'omologazione
    # nazionale, e rispondere con una lista vuota farebbe sembrare che non ci
    # sia niente da collegare.
    assert keys == ["cash_drawer_kick", "escpos_generic"]


def test_the_catalogue_views_are_json_safe():
    json.dumps({
        "devices": fiscal_device_catalogue(),
        "devices_it": fiscal_device_catalogue("IT"),
        "terminals": pos_terminal_catalogue(),
        "terminals_it": pos_terminal_catalogue("IT"),
    })


def test_the_catalogue_claims_no_implementation():
    """Il pacchetto non parla con nessun terminale. Un campo «implementato»
    qui dentro sarebbe una promessa che non può mantenere, e chi lo incorpora
    la leggerebbe come propria."""
    for row in pos_terminal_catalogue():
        assert "implemented" not in row and "status" not in row
    for row in fiscal_device_catalogue():
        assert "implemented" not in row
        # ...ma il suggerimento di nomenclatura del driver sì, ed è dichiarato
        # per quello che è.
        assert "driver_hint" in row


def test_a_closed_system_says_so_instead_of_being_left_out():
    """Flatpay è il caso: terminale e cassa venduti come un blocco solo, senza
    interfaccia pubblica per un registratore di terzi.

    Ometterlo dal catalogo lo farebbe cercare di nuovo alla prossima domanda;
    metterlo senza dire che è chiuso farebbe pianificare un'integrazione che non
    esiste. ``vendor_pos`` è la risposta a entrambe.
    """
    flatpay = POS_TERMINALS["flatpay"]

    assert flatpay.integration == "vendor_pos"
    assert "chiuso" in flatpay.notes
    assert flatpay.docs_url, "chi vuole verificarlo deve sapere dove guardare"


@pytest.mark.parametrize("key", sorted(POS_TERMINALS))
def test_a_closed_terminal_never_claims_a_local_protocol(key):
    """``vendor_pos`` e ``terminal_api`` sono affermazioni opposte: la prima dice
    che non c'è niente da chiamare, la seconda che c'è un protocollo in LAN."""
    terminal = POS_TERMINALS[key]
    if terminal.integration == "vendor_pos":
        assert "lan" not in terminal.connection, key
        assert terminal.notes, f"{key}: un sistema chiuso deve spiegare perché"


# ── chi si può davvero comandare ──────────────────────────────────────
#
# «Integrabile» ha un significato preciso: un sistema esterno avvia un incasso
# in presenza e ne conosce l'esito. Un terminale che sta sul banco accanto alla
# cassa non lo è, per quanto sia un ottimo terminale.


@pytest.mark.parametrize("key", sorted(POS_TERMINALS))
def test_every_capability_comes_from_the_vocabulary(key):
    assert set(POS_TERMINALS[key].capabilities) <= set(TERMINAL_CAPABILITIES)


@pytest.mark.parametrize("key", sorted(POS_TERMINALS))
def test_programmable_means_start_payment_and_nothing_else(key):
    """Il resto — status, webhook, storno — è utile ma non decide: senza
    ``start_payment`` non c'è nessun pagamento da seguire."""
    terminal = POS_TERMINALS[key]

    assert terminal.programmable is ("start_payment" in terminal.capabilities)


@pytest.mark.parametrize("key", sorted(POS_TERMINALS))
def test_a_capability_never_stands_alone_without_starting_a_payment(key):
    """`status` o `webhook` senza `start_payment` descriverebbero un terminale
    di cui si può leggere l'esito di transazioni che non si possono avviare —
    che è reportistica, non integrazione, e va detto con altre parole."""
    terminal = POS_TERMINALS[key]
    if terminal.capabilities:
        assert "start_payment" in terminal.capabilities, key


def test_a_closed_system_declares_no_capabilities():
    assert POS_TERMINALS["flatpay"].capabilities == ()
    assert POS_TERMINALS["flatpay"].programmable is False


def test_the_server_driven_ones_are_the_ones_verified_by_hand():
    """Verificati sulle documentazioni dei fornitori, non a memoria: Stripe
    Terminal, la Cloud API di SumUp sul lettore Solo, le Payment Bridge API di
    Nexi, la Terminal API di Adyen, il callback S2S di Satispay."""
    for key in ("stripe_terminal", "sumup", "nexi", "adyen", "satispay"):
        terminal = POS_TERMINALS[key]
        assert terminal.programmable, key
        assert terminal.public_docs and terminal.docs_url, key


def test_a_push_result_implies_a_way_to_start_the_payment():
    for terminal in POS_TERMINALS.values():
        if terminal.result_is_pushed:
            assert terminal.programmable, terminal.key


def test_programmable_terminals_filters_and_keeps_the_country_order():
    tutti = {t.key for t in programmable_terminals()}

    assert "flatpay" not in tutti
    assert {"stripe_terminal", "sumup", "adyen"} <= tutti
    assert programmable_terminals("IT")[0].countries[0] == "IT", "prima chi nomina il paese"


def test_drivable_devices_leaves_out_what_does_not_print():
    """Le TSE tedesche non stampano: firmano. Elencarle fra i dispositivi
    pilotabili manderebbe qualcuno a cercarne il protocollo di stampa."""
    chiavi = {d.key for d in drivable_devices()}

    assert "swissbit_tse" not in chiavi and "fiskaly_tse" not in chiavi
    assert "epson_rt" in chiavi


def test_the_integrable_view_answers_both_halves_and_says_who_is_out():
    """A un integratore la domanda viene una volta sola; la risposta è diversa
    per i due mondi, e chi resta fuori va nominato — altrimenti lo si ricerca."""
    vista = integrable_devices("IT")

    assert {t["key"] for t in vista["terminals"]} == {
        t.key for t in programmable_terminals("IT")
    }
    assert vista["fiscal_devices"] and vista["vocabulary"]["terminal_capabilities"]
    assert [e["key"] for e in vista["excluded"]] == ["flatpay"]
    assert vista["excluded"][0]["reason"] == "vendor_pos"
    json.dumps(vista)


# ── per che via ci si parla ───────────────────────────────────────────


@pytest.mark.parametrize("key", sorted(POS_TERMINALS))
def test_terminal_channels_come_from_the_vocabulary(key):
    assert set(POS_TERMINALS[key].channels) <= set(INTEGRATION_CHANNELS)


@pytest.mark.parametrize("key", sorted(FISCAL_DEVICE_MODELS))
def test_device_channels_come_from_the_vocabulary(key):
    assert set(FISCAL_DEVICE_MODELS[key].channels) <= set(INTEGRATION_CHANNELS)


def test_a_closed_system_offers_no_integration_channel():
    """Flatpay sta nel cloud come Stripe, ma «raggiungibile via cloud» e
    «integrabile via API» non sono la stessa affermazione. Un elenco filtrato
    per `api` che lo includesse manderebbe qualcuno a cercare un'API che non
    c'è."""
    assert POS_TERMINALS["flatpay"].channels == ()
    assert "flatpay" not in [t.key for t in by_channel("api")["terminals"]]


def test_webhook_is_a_channel_only_where_the_result_really_arrives():
    spinti = {t.key for t in by_channel("webhook")["terminals"]}

    assert spinti == {t.key for t in POS_TERMINALS.values() if t.result_is_pushed}
    assert "worldline" not in spinti, "Worldline va interrogato"


def test_bluetooth_finds_the_handheld_ones():
    chiavi = {t.key for t in by_channel("bluetooth")["terminals"]}

    assert {"sumup", "zettle"} <= chiavi
    assert "stripe_terminal" not in chiavi, "WisePOS E sta in rete, non al polso"


# ── i cassetti ────────────────────────────────────────────────────────


def test_a_cash_drawer_has_no_address_to_knock_on():
    """Il vicolo cieco più comune al banco: cercare il driver del cassetto.

    Un cassetto a impulso è una serratura che scatta quando arrivano 24 V sulla
    porta DK della stampante. Non ha indirizzo, non ha protocollo, non risponde.
    """
    drawer = FISCAL_DEVICE_MODELS["cash_drawer_kick"]

    assert drawer.kind == "cash_drawer"
    assert drawer.channels == ("printer_port",)
    assert drawer.addressable is False
    assert drawer.fiscal is False, "è una scatola, non un dispositivo fiscale"
    assert "si integra la stampante" in drawer.notes


def test_the_drawer_is_listed_apart_from_what_can_be_driven():
    """Metterlo fra i pilotabili lo farebbe cercare lì, che è esattamente
    l'errore che la voce esiste per prevenire."""
    vista = integrable_devices("IT")

    assert "cash_drawer_kick" not in {d["key"] for d in vista["fiscal_devices"]}
    assert [d["key"] for d in vista["not_addressable"]] == ["cash_drawer_kick"]


def test_the_printers_that_can_open_a_drawer_say_so():
    """La capacità sta sulla stampante, che è dove si programma."""
    apribili = {k for k, d in FISCAL_DEVICE_MODELS.items() if "drawer" in d.capabilities}

    assert {"epson_rt", "custom_rt", "escpos_generic"} <= apribili


@pytest.mark.parametrize("key", sorted(FISCAL_DEVICE_MODELS))
def test_every_device_declares_a_known_kind(key):
    assert FISCAL_DEVICE_MODELS[key].kind in DEVICE_KINDS


def test_devices_of_kind_rejects_an_invented_category():
    with pytest.raises(KeyError):
        devices_of_kind("stampante-magica")
