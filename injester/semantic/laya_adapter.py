"""
Laya System-1 Verifier Adapter (Backward Compatibility Layer).
Re-exports LayaVerifier as LayaSystem1Verifier and delegates to the modular verifier engine.
"""

from injester.semantic.verifiers.laya import LayaVerifier, LayaSystem1Verifier
from injester.semantic.schemas import LayaVerdict, System1Verdict

__all__ = [
    "LayaSystem1Verifier",
    "LayaVerifier",
    "LayaVerdict",
    "System1Verdict",
]
