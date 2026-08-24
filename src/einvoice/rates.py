"""VAT rates by country **and by what is being sold**.

A country does not have "a VAT rate". It has a standard rate and a handful of
reduced ones, and which applies depends on the goods or service: in Italy a book
is 4%, a hotel night 10% and a laptop 22%. A package that only knows the list of
rates can tell you 4% exists; it cannot tell you a book should be at 4%, which
is the question anyone building an invoice actually has.

    from einvoice import ProductCategory, rate_for

    rate_for("IT", ProductCategory.BOOKS)          # Decimal("4")
    rate_for("DE", ProductCategory.BOOKS)          # Decimal("7")
    rate_for("GB", ProductCategory.CHILDRENS_CLOTHING)   # Decimal("0")

**How far to trust this.** The rates themselves are the well-published ones and
change rarely; the *category mapping* is where national law gets intricate —
exceptions, thresholds, transitional regimes, and rules that turn on details an
invoice does not carry (is the book educational? is the meal consumed on the
premises?). So:

* everything here is dated by :data:`RATES_VERIFIED_AS_OF`;
* coverage is **deliberately partial** — a category this module cannot state
  with confidence for a country is simply absent, and :func:`rate_for` returns
  ``None`` rather than a guess;
* where a country splits one category across rates on a distinction the invoice
  does not carry (Belgium taxes daily newspapers at 0% and other periodicals at
  6%), the mapping gives the **general** case and the exception is written into
  the rate's ``note``. One category never maps to two rates, or the answer would
  depend on table order;
* nothing here rejects an invoice. It informs
  :meth:`~einvoice.models.Invoice.check`, never :meth:`validate`.

Treat it as the answer a competent colleague would give you before you check
with the accountant — not as the accountant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

__all__ = [
    "RateKind",
    "ProductCategory",
    "VatRate",
    "COUNTRY_RATES",
    "NO_NATIONAL_VAT",
    "COMMONLY_EXEMPT",
    "ALWAYS_STANDARD_RATED",
    "RATES_VERIFIED_AS_OF",
    "rates_for",
    "rate_for",
    "standard_rate",
    "categories_for",
]

#: When these tables were last reviewed. Surfaced by the CLI so nobody mistakes
#: a stale rate for a current one.
RATES_VERIFIED_AS_OF = date(2026, 8, 24)


class RateKind(str, Enum):
    """What *sort* of rate this is, in the EU VAT Directive's own terms.

    The kind matters independently of the number: a "reduced" rate is one a
    member state may apply to the Annex III list, a "parking" rate is a
    transitional one some states kept for goods outside that list, and "zero"
    is a taxable-but-at-zero supply — which is not the same as exempt, because
    it preserves the right to deduct input VAT.
    """

    STANDARD = "standard"
    REDUCED = "reduced"
    SUPER_REDUCED = "super_reduced"
    PARKING = "parking"
    ZERO = "zero"


class ProductCategory(str, Enum):
    """What is being sold, in the vocabulary reduced rates are written in.

    Drawn from Annex III of the VAT Directive (as amended by 2022/542), which is
    the list member states may pick from, plus the few non-EU cases the package
    supports. A category exists here when the invoice can plausibly know it —
    "children's clothing" yes, "book of an educational nature approved by the
    ministry" no.
    """

    STANDARD_GOODS = "standard_goods"
    FOODSTUFFS = "foodstuffs"
    BEVERAGES_ALCOHOLIC = "beverages_alcoholic"
    WATER = "water"
    PHARMACEUTICALS = "pharmaceuticals"
    MEDICAL_EQUIPMENT = "medical_equipment"
    MEDICAL_CARE = "medical_care"
    PASSENGER_TRANSPORT = "passenger_transport"
    BOOKS = "books"
    EBOOKS = "ebooks"
    NEWSPAPERS = "newspapers"
    CULTURAL_ADMISSION = "cultural_admission"
    SPORTING_ADMISSION = "sporting_admission"
    ACCOMMODATION = "accommodation"
    RESTAURANT = "restaurant"
    SOCIAL_HOUSING = "social_housing"
    CONSTRUCTION_RENOVATION = "construction_renovation"
    AGRICULTURAL_INPUTS = "agricultural_inputs"
    ELECTRICITY = "electricity"
    NATURAL_GAS = "natural_gas"
    DISTRICT_HEATING = "district_heating"
    CHILDRENS_CLOTHING = "childrens_clothing"
    HAIRDRESSING = "hairdressing"
    REPAIR_SERVICES = "repair_services"
    SOCIAL_SERVICES = "social_services"
    EDUCATION = "education"
    FINANCIAL_SERVICES = "financial_services"
    INSURANCE = "insurance"
    DIGITAL_SERVICES = "digital_services"


@dataclass(frozen=True)
class VatRate:
    """One rate in force in a country, and what it covers."""

    rate: Decimal
    kind: RateKind
    #: Categories this rate applies to. Empty for the standard rate, which is
    #: the fallback for everything not listed elsewhere.
    categories: tuple[ProductCategory, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.rate, Decimal):        # pragma: no cover - guard
            object.__setattr__(self, "rate", Decimal(str(self.rate)))

    def covers(self, category: ProductCategory) -> bool:
        return category in self.categories


def _r(rate: str, kind: RateKind, *categories: ProductCategory, note: str = "") -> VatRate:
    return VatRate(Decimal(rate), kind, tuple(categories), note)


P = ProductCategory
K = RateKind

# ── the tables ─────────────────────────────────────────────────────────────
# Ordered standard-rate first. A category appears under a country only where it
# can be stated with confidence; the gaps are gaps on purpose.

COUNTRY_RATES: dict[str, tuple[VatRate, ...]] = {
    "IT": (
        _r("22", K.STANDARD),
        _r("10", K.REDUCED, P.ACCOMMODATION, P.RESTAURANT, P.PASSENGER_TRANSPORT,
           P.ELECTRICITY, P.CULTURAL_ADMISSION, P.PHARMACEUTICALS,
           note="Aliquota ridotta ordinaria."),
        _r("5", K.REDUCED,
           note="Alcune prestazioni socio-sanitarie e assistenziali. Non "
                "mappata a una categoria: le cure mediche vere e proprie sono "
                "ESENTI (art. 132 direttiva IVA), non ridotte, e confonderle "
                "darebbe la risposta sbagliata a chi fattura prestazioni."),
        _r("4", K.SUPER_REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.MEDICAL_EQUIPMENT,
           note="Beni di prima necessità, editoria."),
        _r("0", K.ZERO),
    ),
    "DE": (
        _r("19", K.STANDARD),
        _r("7", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.PASSENGER_TRANSPORT, P.ACCOMMODATION, P.CULTURAL_ADMISSION,
           P.AGRICULTURAL_INPUTS,
           note="Ermäßigter Steuersatz."),
        _r("0", K.ZERO, note="Fotovoltaico residenziale dal 2023 (§12 Abs. 3 UStG)."),
    ),
    "FR": (
        _r("20", K.STANDARD),
        _r("10", K.REDUCED, P.RESTAURANT, P.ACCOMMODATION, P.PASSENGER_TRANSPORT,
           P.CONSTRUCTION_RENOVATION, P.CULTURAL_ADMISSION),
        _r("5.5", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.WATER,
           P.MEDICAL_EQUIPMENT, P.SOCIAL_HOUSING, P.ELECTRICITY),
        _r("2.1", K.SUPER_REDUCED, P.PHARMACEUTICALS, P.NEWSPAPERS,
           note="Médicaments remboursables, presse."),
        _r("0", K.ZERO),
    ),
    "ES": (
        _r("21", K.STANDARD),
        _r("10", K.REDUCED, P.FOODSTUFFS, P.PASSENGER_TRANSPORT, P.ACCOMMODATION,
           P.RESTAURANT, P.CULTURAL_ADMISSION, P.WATER),
        _r("4", K.SUPER_REDUCED, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.PHARMACEUTICALS, P.MEDICAL_EQUIPMENT,
           note="Bienes de primera necesidad."),
        _r("0", K.ZERO),
    ),
    "NL": (
        _r("21", K.STANDARD),
        _r("9", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.WATER, P.PASSENGER_TRANSPORT, P.ACCOMMODATION, P.CULTURAL_ADMISSION,
           P.PHARMACEUTICALS, P.REPAIR_SERVICES, P.HAIRDRESSING),
        _r("0", K.ZERO),
    ),
    "BE": (
        _r("21", K.STANDARD),
        _r("12", K.PARKING, P.RESTAURANT, P.SOCIAL_HOUSING),
        _r("6", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.WATER, P.PHARMACEUTICALS, P.PASSENGER_TRANSPORT, P.ACCOMMODATION,
           P.CULTURAL_ADMISSION, P.REPAIR_SERVICES),
        # Belgium splits newspapers by publication frequency: dailies and
        # high-frequency periodicals are zero-rated, the rest sit at 6%. An
        # invoice does not carry that distinction, so NEWSPAPERS maps to the
        # general 6% case above and the exception lives here, in words. Listing
        # the category under both rates would have made the lookup depend on
        # table order — which is what the tests caught.
        _r("0", K.ZERO, note="Quotidiani e periodici ad alta periodicità: "
                             "aliquota zero, distinta dal 6% degli altri periodici."),
    ),
    "AT": (
        _r("20", K.STANDARD),
        _r("13", K.REDUCED, P.CULTURAL_ADMISSION, P.SPORTING_ADMISSION,
           P.AGRICULTURAL_INPUTS),
        _r("10", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.ACCOMMODATION, P.PASSENGER_TRANSPORT, P.PHARMACEUTICALS, P.WATER),
        _r("0", K.ZERO),
    ),
    "PT": (
        _r("23", K.STANDARD),
        _r("13", K.REDUCED, P.RESTAURANT, P.AGRICULTURAL_INPUTS),
        _r("6", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.PHARMACEUTICALS, P.PASSENGER_TRANSPORT, P.ACCOMMODATION, P.WATER),
        _r("0", K.ZERO),
    ),
    "IE": (
        _r("23", K.STANDARD),
        _r("13.5", K.REDUCED, P.CONSTRUCTION_RENOVATION, P.RESTAURANT,
           P.ELECTRICITY, P.NATURAL_GAS, P.REPAIR_SERVICES),
        _r("9", K.REDUCED, P.NEWSPAPERS, P.EBOOKS, P.SPORTING_ADMISSION,
           P.ACCOMMODATION),
        _r("4.8", K.SUPER_REDUCED, P.AGRICULTURAL_INPUTS,
           note="Livestock rate."),
        _r("0", K.ZERO, P.FOODSTUFFS, P.BOOKS, P.CHILDRENS_CLOTHING,
           P.PHARMACEUTICALS, P.WATER,
           note="Ireland zero-rates a notably wide list."),
    ),
    "GB": (
        _r("20", K.STANDARD),
        _r("5", K.REDUCED, P.ELECTRICITY, P.NATURAL_GAS, P.SOCIAL_HOUSING,
           P.CONSTRUCTION_RENOVATION,
           note="Domestic fuel and power, certain residential works."),
        _r("0", K.ZERO, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.CHILDRENS_CLOTHING, P.WATER, P.PASSENGER_TRANSPORT,
           P.MEDICAL_EQUIPMENT,
           note="Zero-rating is broad in the UK and is NOT exemption: input "
                "VAT remains deductible."),
    ),
    "CH": (
        _r("8.1", K.STANDARD),
        _r("3.8", K.REDUCED, P.ACCOMMODATION,
           note="Sondersatz Beherbergung."),
        _r("2.6", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.PHARMACEUTICALS, P.WATER, P.AGRICULTURAL_INPUTS,
           note="Reduzierter Satz."),
        _r("0", K.ZERO),
    ),
    "SE": (
        _r("25", K.STANDARD),
        _r("12", K.REDUCED, P.FOODSTUFFS, P.RESTAURANT, P.ACCOMMODATION),
        _r("6", K.REDUCED, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.PASSENGER_TRANSPORT, P.CULTURAL_ADMISSION, P.SPORTING_ADMISSION),
        _r("0", K.ZERO),
    ),
    "DK": (
        _r("25", K.STANDARD),
        _r("0", K.ZERO, P.NEWSPAPERS,
           note="Denmark has no reduced rate; newspapers are zero-rated."),
    ),
    "FI": (
        _r("25.5", K.STANDARD),
        _r("14", K.REDUCED, P.FOODSTUFFS, P.RESTAURANT, P.AGRICULTURAL_INPUTS),
        _r("10", K.REDUCED, P.BOOKS, P.EBOOKS, P.PHARMACEUTICALS,
           P.PASSENGER_TRANSPORT, P.ACCOMMODATION, P.CULTURAL_ADMISSION,
           P.SPORTING_ADMISSION),
        _r("0", K.ZERO, P.NEWSPAPERS, note="Abbonamenti a quotidiani e periodici."),
    ),
    "PL": (
        _r("23", K.STANDARD),
        _r("8", K.REDUCED, P.PHARMACEUTICALS, P.PASSENGER_TRANSPORT,
           P.ACCOMMODATION, P.RESTAURANT, P.CONSTRUCTION_RENOVATION,
           P.CULTURAL_ADMISSION),
        _r("5", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.WATER, P.AGRICULTURAL_INPUTS),
        _r("0", K.ZERO),
    ),
    "CZ": (
        _r("21", K.STANDARD),
        _r("12", K.REDUCED, P.FOODSTUFFS, P.PHARMACEUTICALS, P.ACCOMMODATION,
           P.PASSENGER_TRANSPORT, P.WATER, P.CONSTRUCTION_RENOVATION,
           note="Unified reduced rate since 2024."),
        _r("0", K.ZERO, P.BOOKS, note="Books zero-rated since 2024."),
    ),
    "HU": (
        _r("27", K.STANDARD, note="The highest standard rate in the EU."),
        _r("18", K.REDUCED, P.FOODSTUFFS, P.ACCOMMODATION),
        _r("5", K.REDUCED, P.PHARMACEUTICALS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.MEDICAL_EQUIPMENT, P.DISTRICT_HEATING),
        _r("0", K.ZERO),
    ),
    "RO": (
        _r("21", K.STANDARD),
        _r("11", K.REDUCED, P.FOODSTUFFS, P.PHARMACEUTICALS, P.BOOKS,
           P.NEWSPAPERS, P.ACCOMMODATION, P.RESTAURANT, P.WATER,
           P.PASSENGER_TRANSPORT, P.CULTURAL_ADMISSION,
           note="Reduced rates consolidated to a single band in 2025."),
        _r("0", K.ZERO),
    ),
    "GR": (
        _r("24", K.STANDARD),
        _r("13", K.REDUCED, P.FOODSTUFFS, P.WATER, P.ACCOMMODATION,
           P.RESTAURANT, P.AGRICULTURAL_INPUTS),
        _r("6", K.REDUCED, P.PHARMACEUTICALS, P.BOOKS, P.NEWSPAPERS,
           P.ELECTRICITY, P.NATURAL_GAS),
        _r("0", K.ZERO),
    ),
    "BG": (
        _r("20", K.STANDARD),
        _r("9", K.REDUCED, P.ACCOMMODATION, P.BOOKS, P.NEWSPAPERS),
        _r("0", K.ZERO),
    ),
    "HR": (
        _r("25", K.STANDARD),
        _r("13", K.REDUCED, P.ACCOMMODATION, P.NEWSPAPERS, P.ELECTRICITY,
           P.WATER, P.RESTAURANT),
        _r("5", K.REDUCED, P.FOODSTUFFS, P.BOOKS, P.PHARMACEUTICALS,
           P.MEDICAL_EQUIPMENT),
        _r("0", K.ZERO),
    ),
    "SI": (
        _r("22", K.STANDARD),
        _r("9.5", K.REDUCED, P.FOODSTUFFS, P.WATER, P.PHARMACEUTICALS,
           P.PASSENGER_TRANSPORT, P.ACCOMMODATION, P.RESTAURANT,
           P.CULTURAL_ADMISSION),
        _r("5", K.REDUCED, P.BOOKS, P.EBOOKS, P.NEWSPAPERS),
        _r("0", K.ZERO),
    ),
    "SK": (
        _r("23", K.STANDARD),
        _r("19", K.REDUCED, P.ELECTRICITY, P.FOODSTUFFS,
           note="Second band introduced in 2025."),
        _r("5", K.REDUCED, P.PHARMACEUTICALS, P.BOOKS, P.ACCOMMODATION,
           P.SOCIAL_HOUSING, P.MEDICAL_EQUIPMENT),
        _r("0", K.ZERO),
    ),
    "LT": (
        _r("21", K.STANDARD),
        _r("9", K.REDUCED, P.ACCOMMODATION, P.PASSENGER_TRANSPORT, P.BOOKS,
           P.NEWSPAPERS, P.DISTRICT_HEATING),
        _r("5", K.REDUCED, P.PHARMACEUTICALS, P.MEDICAL_EQUIPMENT),
        _r("0", K.ZERO),
    ),
    "LV": (
        _r("21", K.STANDARD),
        _r("12", K.REDUCED, P.PHARMACEUTICALS, P.MEDICAL_EQUIPMENT,
           P.PASSENGER_TRANSPORT, P.ACCOMMODATION, P.FOODSTUFFS),
        _r("5", K.REDUCED, P.BOOKS, P.NEWSPAPERS, P.AGRICULTURAL_INPUTS),
        _r("0", K.ZERO),
    ),
    "EE": (
        _r("24", K.STANDARD),
        _r("22", K.REDUCED, note="Transitional band during the 2025-26 increase."),
        _r("9", K.REDUCED, P.BOOKS, P.NEWSPAPERS, P.PHARMACEUTICALS,
           P.ACCOMMODATION),
        _r("0", K.ZERO),
    ),
    "LU": (
        _r("17", K.STANDARD, note="The lowest standard rate in the EU."),
        _r("14", K.PARKING, P.AGRICULTURAL_INPUTS),
        _r("8", K.REDUCED, P.CONSTRUCTION_RENOVATION, P.HAIRDRESSING,
           P.REPAIR_SERVICES, P.ELECTRICITY),
        _r("3", K.SUPER_REDUCED, P.FOODSTUFFS, P.BOOKS, P.EBOOKS, P.NEWSPAPERS,
           P.PHARMACEUTICALS, P.PASSENGER_TRANSPORT, P.RESTAURANT,
           P.CHILDRENS_CLOTHING),
        _r("0", K.ZERO),
    ),
    "CY": (
        _r("19", K.STANDARD),
        _r("9", K.REDUCED, P.ACCOMMODATION, P.RESTAURANT, P.PASSENGER_TRANSPORT),
        _r("5", K.REDUCED, P.FOODSTUFFS, P.PHARMACEUTICALS, P.BOOKS,
           P.NEWSPAPERS, P.SOCIAL_HOUSING),
        _r("0", K.ZERO),
    ),
    "MT": (
        _r("18", K.STANDARD),
        _r("12", K.REDUCED,
           note="Band introduced in 2024 for certain services. Not mapped to a "
                "category: medical care itself is exempt, not reduced."),
        _r("7", K.REDUCED, P.ACCOMMODATION, P.SPORTING_ADMISSION),
        _r("5", K.REDUCED, P.BOOKS, P.NEWSPAPERS, P.MEDICAL_EQUIPMENT,
           P.ELECTRICITY, P.CULTURAL_ADMISSION),
        _r("0", K.ZERO, P.FOODSTUFFS, P.PHARMACEUTICALS),
    ),
    # The United States has no national VAT — see NO_NATIONAL_VAT below. An
    # empty tuple, not a 0% entry: inventing a rate would make every real sales
    # tax look like an anomaly to `Invoice.check()`.
    "US": (),
}

#: Countries with no national VAT system, and why. ``rate_for`` returns ``None``
#: for these, and :meth:`~einvoice.countries.CountryProfile.is_known_vat_rate`
#: accepts any rate — because in these jurisdictions the rate legitimately comes
#: from somewhere this package does not model.
NO_NATIONAL_VAT: dict[str, str] = {
    "US": "Nessuna IVA federale. La sales tax è statale e locale, varia per "
          "giurisdizione e per prodotto, e la determina il motore fiscale del "
          "venditore riga per riga.",
}

#: Categories that carry the **standard rate everywhere** this package covers.
#: Naming them is not padding: "is alcohol reduced-rated with the rest of the
#: food?" is a question people genuinely get wrong, and "no, standard" is a
#: better answer than silence.
ALWAYS_STANDARD_RATED = frozenset({
    ProductCategory.BEVERAGES_ALCOHOLIC,
    ProductCategory.DIGITAL_SERVICES,
})

#: Categories that are typically **exempt** rather than rated, across the EU.
#: Exempt is not zero-rated: it removes the right to deduct input VAT, so the
#: distinction matters to the seller even though both show 0 on the invoice.
COMMONLY_EXEMPT = frozenset({
    ProductCategory.MEDICAL_CARE,
    ProductCategory.EDUCATION,
    ProductCategory.FINANCIAL_SERVICES,
    ProductCategory.INSURANCE,
    ProductCategory.SOCIAL_SERVICES,
})


# ── lookups ────────────────────────────────────────────────────────────────


def rates_for(country_code: str) -> tuple[VatRate, ...]:
    """Every rate in force in a country, standard first."""
    return COUNTRY_RATES.get((country_code or "").upper(), ())


def standard_rate(country_code: str) -> Decimal | None:
    """The country's standard rate, or ``None`` if we carry no table for it."""
    for entry in rates_for(country_code):
        if entry.kind is RateKind.STANDARD:
            return entry.rate
    return None


def rate_for(country_code: str, category: ProductCategory) -> Decimal | None:
    """The rate a country applies to a category, or ``None`` when unmapped.

    ``STANDARD_GOODS`` resolves to the standard rate. Anything not explicitly
    mapped returns ``None`` — deliberately, because the honest answer to "what
    rate does Bulgaria apply to bicycle repairs?" is that this module does not
    know, and a plausible-looking guess in a tax table is worse than a blank.
    """
    if category is ProductCategory.STANDARD_GOODS or category in ALWAYS_STANDARD_RATED:
        return standard_rate(country_code)
    for entry in rates_for(country_code):
        if entry.covers(category):
            return entry.rate
    return None


def categories_for(country_code: str) -> dict[ProductCategory, Decimal]:
    """Every category this module can state a rate for, in one country."""
    out: dict[ProductCategory, Decimal] = {}
    for entry in rates_for(country_code):
        for category in entry.categories:
            out.setdefault(category, entry.rate)
    return out
