"""Format/country adapter layer — renderers.

A renderer turns the neutral :class:`~einvoice.models.Invoice` into a concrete
standard's bytes (FatturaPA XML, UBL/Peppol, …). Rendering is separated from
transport: the same UBL document can go to a PEPPOL Access Point or be exported
to a file.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..errors import RenderError
from ..models import Invoice


@dataclass
class RenderedDocument:
    standard: str          # "fatturapa" | "ubl" | "cii" | …
    content: bytes
    mime: str
    filename: str

    def text(self) -> str:
        return self.content.decode("utf-8")


def require_invoice(document: object, standard: str) -> None:
    """Refuse anything that is not a fiscal document, before any XML exists.

    A quote, a pro forma and a delivery note share most of an invoice's fields,
    so duck typing would happily render one — and a pro forma that reaches SdI
    or a Peppol access point *is* an invoice, one that takes a credit note to
    undo. The type is the only thing that says which is which.
    """
    if isinstance(document, Invoice):
        return
    kind = getattr(getattr(document, "kind", None), "value", type(document).__name__)
    raise RenderError(
        f"{standard}: rappresenta solo fatture e note di credito, non un documento "
        f"'{kind}'. Una pro forma o un preventivo si convertono prima in fattura "
        "(to_invoice), un DDT si fattura con deferred_invoice()."
    )


def first_reference(invoice: Invoice, kind: str):
    """EN 16931 allows ONE contract (BT-12) and ONE despatch advice (BT-16)
    reference per document (UBL-SR-01/03); the others stay in the model and
    in FatturaPA, which carries any number of them."""
    return next((r for r in invoice.references if r.kind == kind), None)


class InvoiceRenderer(ABC):
    standard: str = "base"

    @abstractmethod
    def render(self, invoice: Invoice) -> RenderedDocument: ...


_RENDERERS: dict[str, type[InvoiceRenderer]] = {}


def register_renderer(standard: str, cls: type[InvoiceRenderer]) -> None:
    _RENDERERS[standard.lower()] = cls


def available_renderers() -> list[str]:
    return sorted(_RENDERERS)


def get_renderer(standard: str, **kwargs) -> InvoiceRenderer:
    cls = _RENDERERS.get((standard or "").lower())
    if cls is None:
        raise RenderError(
            f"Renderer sconosciuto: {standard!r}. Disponibili: {', '.join(available_renderers())}"
        )
    return cls(**kwargs)
