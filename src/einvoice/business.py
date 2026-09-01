"""What *kind of business* this is, and what that implies for VAT.

Two different planes of rule live in this package, and confusing them is the
mistake this module exists to prevent.

**What you sell** is :class:`~einvoice.rates.ProductCategory`, mapped to a rate
country by country in :mod:`einvoice.rates`. That table is dated, deliberately
partial, and the only place a national rate is stated. Nothing here restates
it: a business type resolves *through* it.

**What you are** is this module. A travel agent taxes its margin and not the
price (Articles 306-310), a farmer may charge flat-rate compensation instead of
VAT (295-305), a dealer in second-hand goods taxes the margin (311-325) — rules
that attach to the activity, not to the article sold, and that no amount of
category mapping can express.

So :func:`business_profile` answers "what does a gym in Belgium charge?" by
looking up the categories a gym supplies in the Belgian rate table, and returns
the special schemes that attach to the activity separately. Nothing is invented
per country: if the table has no answer, neither does this.

**What this is not.** It does not carry national thresholds, national scheme
options or national exemptions. Member states choose whether to offer the
flat-rate farmer scheme at all, set their own SME turnover limits, and exempt
different sports bodies from one another. Encoding those here would mean a
second table of national law, unverified, that contradicts the first one the
day either moves — which is exactly the divergence
:mod:`einvoice.reference` was written to end.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .i18n import translate
from .rates import COMMONLY_EXEMPT, ProductCategory, rate_for, standard_rate

__all__ = [
    "VatScheme",
    "BusinessType",
    "BusinessProfile",
    "SuppliedCategory",
    "business_supplies",
    "business_schemes",
    "business_profile",
    "business_types",
]


class VatScheme(str, Enum):
    """A VAT regime that attaches to an **activity**, not to what is sold.

    The article numbers are Directive 2006/112/EC. They are here because they
    are the only stable handle: thresholds and options move, the articles do
    not, and an integrator who has to ask an accountant needs to name the thing.
    """

    #: Articles 282-292d — turnover below the national limit, no VAT charged.
    #: Every member state sets its own limit, and since 2025 there is also a
    #: cross-border scheme with a Union-wide turnover cap.
    SMALL_ENTERPRISE = "small_enterprise"

    #: Articles 295-305 — the farmer charges flat-rate compensation instead of
    #: VAT and deducts nothing. Optional for member states.
    FARMER_FLAT_RATE = "farmer_flat_rate"

    #: Articles 306-310 (TOMS) — VAT falls on the margin, not the price, and
    #: input VAT on the travel services bought in is not deductible.
    TRAVEL_MARGIN = "travel_margin"

    #: Articles 311-325 — second-hand goods, works of art, collectors' items:
    #: again the margin, not the price.
    SECOND_HAND_MARGIN = "second_hand_margin"

    #: Articles 344-356 — investment gold is exempt, with a right of option.
    INVESTMENT_GOLD = "investment_gold"

    #: Articles 132/135 — activities exempt in the public interest or by
    #: nature (medical care, education, finance, insurance). Exempt is **not**
    #: zero-rated: the right to deduct input VAT is lost.
    EXEMPT_ACTIVITY = "exempt_activity"


class BusinessType(str, Enum):
    """The activity a taxable person carries on.

    Deliberately coarse. The list answers "which rate do I charge and which
    scheme might apply", not "what is my NACE code": a finer split would
    promise a precision the rate table cannot honour.
    """

    RESTAURANT = "restaurant"
    BAR_CAFE = "bar_cafe"
    TAKEAWAY_FOOD = "takeaway_food"
    CATERING = "catering"
    NIGHTCLUB = "nightclub"
    HOTEL = "hotel"
    CAMPSITE = "campsite"
    GYM = "gym"
    SPORTS_CLUB = "sports_club"
    HAIRDRESSER = "hairdresser"
    BEAUTY_SALON = "beauty_salon"
    FOOD_RETAIL = "food_retail"
    BAKERY = "bakery"
    WINERY = "winery"
    FARM = "farm"
    PHARMACY = "pharmacy"
    MEDICAL_PRACTICE = "medical_practice"
    VETERINARY = "veterinary"
    BOOKSHOP = "bookshop"
    CULTURAL_VENUE = "cultural_venue"
    EDUCATION_SCHOOL = "education_school"
    DRIVING_SCHOOL = "driving_school"
    CHILDCARE = "childcare"
    TRAVEL_AGENCY = "travel_agency"
    PASSENGER_TRANSPORT = "passenger_transport"
    VEHICLE_REPAIR = "vehicle_repair"
    CONSTRUCTION = "construction"
    SECOND_HAND_DEALER = "second_hand_dealer"
    SOFTWARE_IT = "software_it"
    FINANCIAL_SERVICES = "financial_services"
    INSURANCE_BROKER = "insurance_broker"
    RETAIL_GENERAL = "retail_general"
    UTILITIES = "utilities"


C = ProductCategory

#: What each activity typically supplies, **most defining first**.
#:
#: An empty tuple is not an oversight: it means the activity has nothing in
#: Annex III and is standard-rated throughout. Saying so beats attaching a
#: category that only half fits, because the half that does not fit is the one
#: that ends up on an invoice.
_SUPPLIES: dict[BusinessType, tuple[ProductCategory, ...]] = {
    BusinessType.RESTAURANT: (C.RESTAURANT, C.BEVERAGES_ALCOHOLIC, C.FOODSTUFFS),
    BusinessType.BAR_CAFE: (C.RESTAURANT, C.BEVERAGES_ALCOHOLIC, C.FOODSTUFFS),
    # Da asporto: la cessione è di alimenti, non un servizio di ristorazione —
    # ed è la distinzione che in molti Stati cambia l'aliquota.
    BusinessType.TAKEAWAY_FOOD: (C.FOODSTUFFS, C.RESTAURANT, C.BEVERAGES_ALCOHOLIC),
    BusinessType.CATERING: (C.RESTAURANT, C.FOODSTUFFS, C.BEVERAGES_ALCOHOLIC),
    BusinessType.NIGHTCLUB: (C.BEVERAGES_ALCOHOLIC, C.CULTURAL_ADMISSION),
    BusinessType.HOTEL: (C.ACCOMMODATION, C.RESTAURANT, C.BEVERAGES_ALCOHOLIC),
    BusinessType.CAMPSITE: (C.ACCOMMODATION,),
    BusinessType.GYM: (C.SPORTING_ADMISSION,),
    BusinessType.SPORTS_CLUB: (C.SPORTING_ADMISSION,),
    BusinessType.HAIRDRESSER: (C.HAIRDRESSING,),
    # L'estetica NON è il parrucchiere dell'Allegato III: dove non è nominata
    # resta ad aliquota ordinaria.
    BusinessType.BEAUTY_SALON: (),
    BusinessType.FOOD_RETAIL: (C.FOODSTUFFS, C.BEVERAGES_ALCOHOLIC, C.WATER),
    BusinessType.BAKERY: (C.FOODSTUFFS,),
    BusinessType.WINERY: (C.BEVERAGES_ALCOHOLIC,),
    BusinessType.FARM: (C.FOODSTUFFS, C.AGRICULTURAL_INPUTS),
    BusinessType.PHARMACY: (C.PHARMACEUTICALS, C.MEDICAL_EQUIPMENT),
    BusinessType.MEDICAL_PRACTICE: (C.MEDICAL_CARE,),
    # L'esenzione dell'art. 132(1)(c) è per le cure **alle persone**: le
    # prestazioni veterinarie non vi rientrano. Alcuni Stati applicano
    # comunque un'aliquota ridotta ad alcune di esse, ma l'Allegato III non ha
    # una voce che questo pacchetto sappia mappare, quindi qui si resta
    # sull'ordinaria invece di attaccare una categoria che calza a metà.
    # (I *medicinali* veterinari sono un'altra cosa: quelli stanno in
    # ``pharmaceuticals``.)
    BusinessType.VETERINARY: (),
    BusinessType.BOOKSHOP: (C.BOOKS, C.NEWSPAPERS, C.EBOOKS),
    BusinessType.CULTURAL_VENUE: (C.CULTURAL_ADMISSION,),
    BusinessType.EDUCATION_SCHOOL: (C.EDUCATION,),
    # Le autoscuole non sono «istruzione scolastica» esente: Corte di
    # giustizia UE, C-449/17 del 14 marzo 2019 (patenti B e C1). Restano
    # imponibili, e questo è il genere di dettaglio che una tabella scritta a
    # occhio sbaglia.
    BusinessType.DRIVING_SCHOOL: (),
    BusinessType.CHILDCARE: (C.SOCIAL_SERVICES,),
    BusinessType.TRAVEL_AGENCY: (C.PASSENGER_TRANSPORT, C.ACCOMMODATION),
    BusinessType.PASSENGER_TRANSPORT: (C.PASSENGER_TRANSPORT,),
    BusinessType.VEHICLE_REPAIR: (C.REPAIR_SERVICES,),
    BusinessType.CONSTRUCTION: (C.CONSTRUCTION_RENOVATION, C.SOCIAL_HOUSING),
    BusinessType.SECOND_HAND_DEALER: (),
    BusinessType.SOFTWARE_IT: (C.DIGITAL_SERVICES,),
    BusinessType.FINANCIAL_SERVICES: (C.FINANCIAL_SERVICES,),
    BusinessType.INSURANCE_BROKER: (C.INSURANCE,),
    BusinessType.RETAIL_GENERAL: (C.STANDARD_GOODS,),
    BusinessType.UTILITIES: (C.ELECTRICITY, C.NATURAL_GAS, C.WATER, C.DISTRICT_HEATING),
}

#: I regimi che si attaccano all'attività. ``SMALL_ENTERPRISE`` non è elencato
#: perché **riguarda chiunque** stia sotto la soglia: dirlo per ogni voce
#: sarebbe rumore, e ometterlo dove vale sarebbe una bugia — sta in
#: :func:`business_schemes` per tutti.
_SCHEMES: dict[BusinessType, tuple[VatScheme, ...]] = {
    BusinessType.TRAVEL_AGENCY: (VatScheme.TRAVEL_MARGIN,),
    BusinessType.FARM: (VatScheme.FARMER_FLAT_RATE,),
    BusinessType.SECOND_HAND_DEALER: (VatScheme.SECOND_HAND_MARGIN,),
    BusinessType.MEDICAL_PRACTICE: (VatScheme.EXEMPT_ACTIVITY,),
    BusinessType.EDUCATION_SCHOOL: (VatScheme.EXEMPT_ACTIVITY,),
    BusinessType.CHILDCARE: (VatScheme.EXEMPT_ACTIVITY,),
    BusinessType.FINANCIAL_SERVICES: (VatScheme.EXEMPT_ACTIVITY,),
    BusinessType.INSURANCE_BROKER: (VatScheme.EXEMPT_ACTIVITY,),
}


@dataclass(frozen=True)
class SuppliedCategory:
    """One thing the business sells, and what the country charges on it."""

    category: ProductCategory
    #: ``None`` quando il paese non mappa la categoria **e** non ha
    #: un'ordinaria da applicare: non è zero, è «non lo so».
    rate: str | None
    #: Vero quando la categoria è tipicamente esente: niente aliquota, e il
    #: diritto alla detrazione si perde. Non è lo stesso che «zero».
    exempt: bool
    #: Vero per la categoria che definisce l'attività (la prima).
    primary: bool


@dataclass(frozen=True)
class BusinessProfile:
    """Cosa fattura un'attività in un paese, ricavato da dati già datati."""

    business: BusinessType
    country: str
    supplies: tuple[SuppliedCategory, ...]
    schemes: tuple[VatScheme, ...]
    standard: str | None


def business_supplies(business: BusinessType) -> tuple[ProductCategory, ...]:
    """Le categorie che l'attività cede, la più caratterizzante per prima."""
    return _SUPPLIES[business]


def business_schemes(business: BusinessType) -> tuple[VatScheme, ...]:
    """I regimi speciali che si attaccano all'attività.

    ``SMALL_ENTERPRISE`` c'è sempre: sotto soglia riguarda chiunque, e non
    dirlo su un'attività piccola sarebbe l'omissione che costa.
    """
    return (*_SCHEMES.get(business, ()), VatScheme.SMALL_ENTERPRISE)


def business_profile(
    business: BusinessType | str, country: str, locale: str | None = None
) -> dict[str, Any]:
    """Che aliquote applica **questa** attività in **questo** paese.

    Le aliquote non sono dichiarate qui: si risolvono nella tabella per paese
    di :mod:`einvoice.rates`, che è l'unica datata. Una categoria che quel
    paese non mappa ricade sull'aliquota ordinaria — e se il paese non ha
    nemmeno quella (Stati Uniti), resta ``None``, perché lì l'imposta la
    determina un motore che questo pacchetto non modella.

    :raises KeyError: il tipo di attività non esiste.
    """
    tipo = BusinessType(business)
    codice = (country or "").upper()
    ordinaria = standard_rate(codice)

    voci: list[dict[str, Any]] = []
    for indice, categoria in enumerate(business_supplies(tipo)):
        esente = categoria in COMMONLY_EXEMPT
        aliquota = None if esente else rate_for(codice, categoria)
        if aliquota is None and not esente:
            aliquota = ordinaria
        voci.append(
            {
                "category": categoria.value,
                "category_label": translate(f"product_category.{categoria.value}", locale)
                or categoria.value,
                "rate": None if aliquota is None else str(aliquota),
                "exempt": esente,
                "primary": indice == 0,
            }
        )

    schemi = business_schemes(tipo)
    return {
        "business": tipo.value,
        "business_label": translate(f"business_type.{tipo.value}", locale) or tipo.value,
        "country": codice,
        "standard_rate": None if ordinaria is None else str(ordinaria),
        "supplies": voci,
        "schemes": [
            {
                "value": s.value,
                "label": translate(f"vat_scheme.{s.value}", locale) or s.value,
                "articles": _ARTICLES[s],
            }
            for s in schemi
        ],
    }


#: Gli articoli della direttiva 2006/112/CE. Sono l'unico appiglio stabile:
#: soglie e opzioni si muovono, i numeri d'articolo no.
_ARTICLES: dict[VatScheme, str] = {
    VatScheme.SMALL_ENTERPRISE: "282-292d",
    VatScheme.FARMER_FLAT_RATE: "295-305",
    VatScheme.TRAVEL_MARGIN: "306-310",
    VatScheme.SECOND_HAND_MARGIN: "311-325",
    VatScheme.INVESTMENT_GOLD: "344-356",
    VatScheme.EXEMPT_ACTIVITY: "132, 135",
}


def business_types(locale: str | None = None) -> list[dict[str, Any]]:
    """Il vocabolario delle attività, per una tendina."""
    return [
        {
            "value": b.value,
            "label": translate(f"business_type.{b.value}", locale) or b.value,
            "supplies": [c.value for c in business_supplies(b)],
        }
        for b in sorted(BusinessType, key=lambda b: b.value)
    ]
