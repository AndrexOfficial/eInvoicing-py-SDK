"""Exception hierarchy for the e-invoice module.

Kept tiny and dependency-free so hosting platforms can catch a single base
(:class:`EInvoiceError`) or the specific subclasses.
"""
from __future__ import annotations


class EInvoiceError(Exception):
    """Base class for every error raised by this module."""


class ValidationError(EInvoiceError):
    """The invoice / party data is incomplete or inconsistent (raised before
    we ever hit the network or build XML)."""


class ProviderConfigError(EInvoiceError):
    """A provider was asked to do network I/O without the credentials /
    configuration it needs."""


class ProviderError(EInvoiceError):
    """A transport/provider returned an error (HTTP, SDI rejection, auth …).

    Carries the normalized ``status`` and the raw provider payload so callers
    can log / surface the detail without re-parsing.
    """

    def __init__(self, message: str, *, status: str = "error", raw: dict | None = None):
        super().__init__(message)
        self.status = status
        self.raw = raw or {}


# Backwards-friendly alias: the transport layer raises the same type.
TransportError = ProviderError


class RenderError(EInvoiceError):
    """A country/format renderer could not produce the document."""


class IllegalTransition(EInvoiceError):
    """An invoice lifecycle transition is not allowed from the current state."""
