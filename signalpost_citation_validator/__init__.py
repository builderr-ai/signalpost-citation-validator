"""Byte-linkage validation for Signalpost result envelopes.

The validator checks that claims point to captured snapshot files whose bytes
match the SHA-256 digests recorded in the envelope's evidence metadata. It does
not decide whether a claim is factually true, whether a source belongs to a
particular company, or how a competition entry should score. It performs no
network requests.
"""

from __future__ import annotations

from .validator import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    VALIDATOR_ID,
    EnvelopeResult,
    Finding,
    validate_envelope,
    validate_input,
)

__all__ = [
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "VALIDATOR_ID",
    "EnvelopeResult",
    "Finding",
    "validate_envelope",
    "validate_input",
]
