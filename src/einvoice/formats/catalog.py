"""What each renderer *is* — the half a registry key does not tell you.

:func:`~einvoice.formats.base.available_renderers` answers with six strings:
``cii``, ``facturx``, ``fatturapa``, ``peppol``, ``ubl``, ``zugferd``. That is
enough to construct one and nowhere near enough to *choose* one — three of
those six are aliases of the same class, and the difference between the other
three is the difference between a document that is accepted and one that is
refused at the door.

Both embedded products were putting that raw list in front of an operator, so
"pick a format" meant picking between two spellings of CII and hoping. This
module says which is which: the syntax underneath, the national profiles it can
be narrowed to, the file it produces, and the markets that actually take it.

    from einvoice.formats.catalog import renderer_spec, RENDERER_SPECS

    renderer_spec("zugferd").standard        # 'cii' — the alias resolved
    renderer_spec("ubl").profiles            # the four CIUS it can carry

The *localized* names and descriptions live in :mod:`einvoice.i18n`; what is
here is structure, which does not change per language.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import RenderError
from .base import available_renderers

__all__ = ["RendererSpec", "RENDERER_SPECS", "renderer_spec", "renderers_for_country"]


@dataclass(frozen=True)
class RendererProfile:
    """A narrowing of a syntax to one recipient's rule set.

    Not a separate renderer: same class, a different ``customization`` /
    ``guideline`` identifier stamped into the document. Getting it wrong is the
    quiet failure mode — the XML is valid EN 16931 and the German B2G portal
    still refuses it because it wanted XRechnung.
    """

    key: str
    name: str
    #: Where it is required, ``()`` when it is a general-purpose default.
    countries: tuple[str, ...] = ()
    #: How to ask this package for it.
    how: str = ""


@dataclass(frozen=True)
class RendererSpec:
    """One document format the package can produce."""

    key: str
    #: Registry key of the underlying implementation. Equals ``key`` except for
    #: aliases, where it names what the alias really is.
    standard: str
    #: The syntax as a standards body would name it.
    syntax: str
    #: Other registry keys resolving to the same renderer.
    aliases: tuple[str, ...] = ()
    mime: str = "application/xml"
    extension: str = ".xml"
    #: Markets that accept it. ``"EU"`` for the EN 16931 syntaxes, which are
    #: not tied to one country.
    countries: tuple[str, ...] = ("EU",)
    profiles: tuple[RendererProfile, ...] = ()
    docs_url: str = ""
    #: Keyword arguments :func:`~einvoice.formats.base.get_renderer` accepts.
    options: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_alias(self) -> bool:
        return self.key != self.standard


_PEPPOL = RendererProfile(
    key="peppol_bis", name="Peppol BIS Billing 3.0",
    how="renderer_for_country('<CC>')",
)
_XRECHNUNG = RendererProfile(
    key="xrechnung", name="XRechnung 3.0", countries=("DE",),
    how="renderer_for_country('DE', b2g=True)",
)
_NLCIUS = RendererProfile(
    key="nlcius", name="NLCIUS", countries=("NL",),
    how="renderer_for_country('NL', b2g=True)",
)
_CIUS_RO = RendererProfile(
    key="cius_ro", name="CIUS-RO", countries=("RO",),
    how="renderer_for_country('RO')",
)

RENDERER_SPECS: dict[str, RendererSpec] = {
    "fatturapa": RendererSpec(
        key="fatturapa", standard="fatturapa", syntax="FatturaPA 1.2.2",
        countries=("IT",),
        docs_url="https://www.fatturapa.gov.it/it/norme-e-regole/documentazione-fattura-elettronica/",
        options=("progressivo_invio", "trasmittente_country", "trasmittente_id"),
        profiles=(
            RendererProfile(key="ordinaria", name="Fattura ordinaria (TD01–TD28)",
                            countries=("IT",)),
        ),
    ),
    "ubl": RendererSpec(
        key="ubl", standard="ubl", syntax="OASIS UBL 2.1 (EN 16931)",
        aliases=("peppol",),
        docs_url="https://docs.peppol.eu/poacc/billing/3.0/",
        options=("customization", "tax_scheme"),
        profiles=(_PEPPOL, _XRECHNUNG, _NLCIUS, _CIUS_RO),
    ),
    "peppol": RendererSpec(
        key="peppol", standard="ubl", syntax="OASIS UBL 2.1 (EN 16931)",
        docs_url="https://docs.peppol.eu/poacc/billing/3.0/",
        options=("customization", "tax_scheme"),
        profiles=(_PEPPOL,),
    ),
    "cii": RendererSpec(
        key="cii", standard="cii", syntax="UN/CEFACT CII D16B (EN 16931)",
        aliases=("facturx", "zugferd"),
        docs_url="https://fnfe-mpe.org/factur-x/",
        options=("guideline", "profile", "tax_scheme", "customization"),
        profiles=(
            RendererProfile(key="factur_x", name="Factur-X / ZUGFeRD (minimum → extended)",
                            countries=("FR", "DE")),
            RendererProfile(key="chorus_pro", name="Chorus Pro", countries=("FR",),
                            how="renderer_for_country('FR', standard='cii')"),
            RendererProfile(key="xrechnung_cii", name="XRechnung 3.0 on CII",
                            countries=("DE",),
                            how="get_renderer('cii', profile='xrechnung')"),
        ),
    ),
    "facturx": RendererSpec(
        key="facturx", standard="cii", syntax="UN/CEFACT CII D16B (EN 16931)",
        countries=("FR", "DE", "EU"), docs_url="https://fnfe-mpe.org/factur-x/",
        options=("guideline", "profile", "tax_scheme", "customization"),
    ),
    "zugferd": RendererSpec(
        key="zugferd", standard="cii", syntax="UN/CEFACT CII D16B (EN 16931)",
        countries=("DE", "EU"), docs_url="https://www.ferd-net.de/",
        options=("guideline", "profile", "tax_scheme", "customization"),
    ),
}


def renderer_spec(key: str) -> RendererSpec:
    """Describe one renderer.

    :raises RenderError: unknown key — same error type the registry raises, so
        a caller that already handles "unknown renderer" needs no second branch.
    """
    spec = RENDERER_SPECS.get((key or "").lower())
    if spec is None:
        raise RenderError(
            f"Renderer sconosciuto: {key!r}. Disponibili: {', '.join(sorted(RENDERER_SPECS))}"
        )
    return spec


def renderers_for_country(code: str) -> list[RendererSpec]:
    """The formats a seller in ``code`` may actually emit, national one first.

    Two exclusions, both deliberate:

    *Aliases.* Offering ``facturx`` and ``zugferd`` as separate choices when
    both build the same bytes is a menu that invites a coin flip.

    *Other countries' national formats.* FatturaPA does not appear for a French
    seller. It is not merely a worse choice there, it is a guaranteed rejection,
    and a picker that lists guaranteed rejections is a picker that will be used
    to make one.
    """
    country = (code or "").upper()
    canonical = [s for s in RENDERER_SPECS.values() if not s.is_alias and s.key != "peppol"]
    national = [s for s in canonical if country in s.countries]
    universal = [s for s in canonical if "EU" in s.countries and country not in s.countries]
    return national + universal


def _assert_registry_agreement() -> list[str]:
    """Keys described here that the renderer registry cannot build.

    A spec for a renderer nobody can instantiate is a menu entry that 500s when
    picked; the package's tests call this rather than trusting the two lists to
    stay aligned by hand.
    """
    return sorted(set(RENDERER_SPECS) - set(available_renderers()))
