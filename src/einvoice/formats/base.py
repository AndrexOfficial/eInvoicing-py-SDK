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
