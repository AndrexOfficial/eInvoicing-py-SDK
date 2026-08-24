"""Transport adapter layer.

A transport delivers a :class:`~einvoice.formats.base.RenderedDocument` over a
channel — SdI (via intermediary/provider), a PEPPOL Access Point, a portal API,
or a plain file export — and normalizes outcomes (esiti) into
:class:`~einvoice.lifecycle.Notification`. Signing and conservazione are pluggable
via the :class:`Signer` / :class:`ArchiveStore` protocols.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..formats.base import RenderedDocument
from ..lifecycle import Notification
from ..models import Invoice

# Normalized transport statuses.
STATUS_EXPORTED = "exported"
STATUS_SUBMITTED = "submitted"
STATUS_PENDING = "pending"
STATUS_DELIVERED = "delivered"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_NOT_DELIVERED = "not_delivered"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"


@dataclass
class TransportConfig:
    name: str
    base_url: str | None = None
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    company_id: str | None = None
    sandbox: bool = True
    timeout: float = 30.0
    extra: dict = field(default_factory=dict)


# Back-compat alias.
ProviderConfig = TransportConfig


@dataclass
class SubmissionResult:
    transport: str
    status: str
    provider_id: str | None = None
    sdi_id: str | None = None
    filename: str | None = None
    message: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class TransportStatus:
    transport: str
    provider_id: str | None
    status: str
    sdi_id: str | None = None
    sdi_status: str | None = None
    message: str | None = None
    raw: dict = field(default_factory=dict)


InvoiceStatus = TransportStatus  # back-compat alias


@runtime_checkable
class Signer(Protocol):
    """Applies a qualified electronic signature (CAdES ``.p7m`` / XAdES)."""

    def sign(self, content: bytes, *, filename: str) -> tuple[bytes, str]:
        """Return ``(signed_bytes, signed_filename)``."""
        ...


@runtime_checkable
class ArchiveStore(Protocol):
    """Stores the document for conservazione a norma / audit."""

    async def store(self, rendered: RenderedDocument, invoice: Invoice, *,
                    result: SubmissionResult | None = None) -> str:
        """Return an archive reference (path / id)."""
        ...


class FileArchive:
    """Minimal :class:`ArchiveStore` — writes the document to a directory.

    NOT certified conservazione a norma (that's a regulated 10-year service);
    a usable default for dev / audit export and a template for a real adapter.
    """

    def __init__(self, directory: str):
        self.directory = directory

    async def store(self, rendered, invoice, *, result=None) -> str:
        os.makedirs(self.directory, exist_ok=True)
        path = os.path.join(self.directory, rendered.filename)
        with open(path, "wb") as fh:
            fh.write(rendered.content)
        return path


class Transport(ABC):
    name: str = "base"

    def __init__(self, config: TransportConfig):
        self.config = config

    @abstractmethod
    async def transmit(self, rendered: RenderedDocument, invoice: Invoice) -> SubmissionResult: ...

    @abstractmethod
    async def fetch_status(self, provider_id: str) -> TransportStatus: ...

    def parse_notification(self, payload: dict) -> Notification | None:
        """Normalize a provider webhook/notification payload. Default: none."""
        return None
