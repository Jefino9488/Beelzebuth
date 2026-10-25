"""
Unit Tests for System-1 Decision Verifiers and Policy Layer.
Verifies interface compliance, policy decoupling, fallback behavior, and backward compatibility.
"""

import pytest
from injester.semantic.schemas import (
    AtomicProposition,
    System1Verdict,
    LayaVerdict,
    RawTypedDecisions,
    GroundingVerdict,
    ModalityType,
    EpistemicStatus,
)
from injester.synthesis.spans import SourceSpan, SpanRegistry
from injester.semantic.verifiers import (
    System1Verifier,
    System1ValidationPolicy,
    LayaVerifier,
    JevVerifier,
    OpenJevVerifier,
    get_system1_verifier,
)


@pytest.fixture
def mock_span_registry():
    registry = SpanRegistry()
    registry.spans_by_id["S1"] = SourceSpan(
        span_id="S1",
        chunk_id="c1",
        source_doc="test.txt",
        text="The employee must submit the application through the portal."
    )
    return registry


def test_system1_policy_thresholds_and_verdicts():
    """Verifies that System1ValidationPolicy evaluates raw continuous decisions into typed verdicts."""
    policy = System1ValidationPolicy(
        actor_threshold=0.50,
        action_threshold=0.50,
        outcome_threshold=0.40,
        uncertain_threshold=0.35
    )

    prop = AtomicProposition(
        id="P1",
        actor_claim="Employee",
        action_verb="submit",
        target_object="application",
        modality=ModalityType.MANDATORY,
        epistemic_status=EpistemicStatus.CONFIRMED,
        evidence_spans=["S1"]
    )

    # 1. Fully supported case
    raw_supported = RawTypedDecisions(
        actor_p=0.92,
        action_p=0.88,
        modality_choice="mandatory",
        epistemic_choice="confirmed"
    )
    v1 = policy.evaluate(prop, raw_supported, provider="jev")
    assert v1.verdict == GroundingVerdict.SUPPORTED
    assert v1.is_verified is True
    assert v1.actor_grounded is True
    assert v1.action_entailed is True
    assert len(v1.rejection_reasons) == 0

    # 2. Deontic escalation case: Claimed mandatory, evidence says permissive
    raw_escalated = RawTypedDecisions(
        actor_p=0.85,
        action_p=0.85,
        modality_choice="permissive",
        epistemic_choice="confirmed"
    )
    v2 = policy.evaluate(prop, raw_escalated, provider="jev")
    assert v2.verdict == GroundingVerdict.UNSUPPORTED
    assert v2.is_verified is False
    assert v2.is_modality_escalated is True
    assert any("Deontic escalation" in r for r in v2.rejection_reasons)

    # 3. Negative record inversion: Evidence indicates absent record
    raw_inverted = RawTypedDecisions(
        actor_p=0.80,
        action_p=0.80,
        modality_choice="mandatory",
        epistemic_choice="unrecorded"
    )
    v3 = policy.evaluate(prop, raw_inverted, provider="jev")
    assert v3.verdict == GroundingVerdict.UNSUPPORTED
    assert v3.is_verified is False
    assert v3.is_epistemic_inverted is True
    assert any("Negative record inversion" in r for r in v3.rejection_reasons)

    # 4. Uncertain range: probability between 0.35 and 0.50
    raw_uncertain = RawTypedDecisions(
        actor_p=0.42,
        action_p=0.75,
        modality_choice="mandatory",
        epistemic_choice="confirmed"
    )
    v4 = policy.evaluate(prop, raw_uncertain, provider="jev")
    assert v4.verdict == GroundingVerdict.UNCERTAIN
    assert v4.is_verified is False


def test_system1_policy_threshold_sensitivity():
    """Verifies that changing policy thresholds tunes behavior outside model adapters."""
    strict_policy = System1ValidationPolicy(actor_threshold=0.80, action_threshold=0.80)
    lenient_policy = System1ValidationPolicy(actor_threshold=0.40, action_threshold=0.40)

    prop = AtomicProposition(
        id="P1",
        actor_claim="Manager",
        action_verb="approve",
        target_object="request",
        evidence_spans=["S1"]
    )
    raw = RawTypedDecisions(actor_p=0.65, action_p=0.65)

    strict_verdict = strict_policy.evaluate(prop, raw)
    assert strict_verdict.is_verified is False

    lenient_verdict = lenient_policy.evaluate(prop, raw)
    assert lenient_verdict.is_verified is True


def test_system1_verifier_interface_compliance():
    """Verifies that all verifiers adhere to the generic System1Verifier ABC."""
    for cls in (LayaVerifier, JevVerifier, OpenJevVerifier):
        assert issubclass(cls, System1Verifier)
        verifier = cls()
        assert hasattr(verifier, "verify_propositions")
        assert callable(verifier.verify_propositions)


def test_jev_verifier_structural_fallback(mock_span_registry):
    """Verifies JevVerifier cleanly falls back to structural check when unauthenticated."""
    jev = JevVerifier(api_key=None)

    valid_prop = AtomicProposition(
        id="P1",
        actor_claim="Employee",
        action_verb="submit",
        target_object="leave",
        evidence_spans=["S1"]
    )
    missing_prop = AtomicProposition(
        id="P2",
        actor_claim="Employee",
        action_verb="notify",
        target_object="hr",
        evidence_spans=["S_NONEXISTENT"]
    )

    verdicts = jev.verify_propositions([valid_prop, missing_prop], mock_span_registry)

    assert verdicts["P1"].verdict == GroundingVerdict.SUPPORTED
    assert verdicts["P1"].is_verified is True
    assert "jev" in verdicts["P1"].provider

    assert verdicts["P2"].verdict == GroundingVerdict.UNSUPPORTED
    assert verdicts["P2"].is_verified is False
    assert any("lacks cited evidence" in r for r in verdicts["P2"].rejection_reasons)


def test_openjev_verifier_structural_fallback(mock_span_registry):
    """Verifies OpenJevVerifier structural fallback behavior."""
    openjev = OpenJevVerifier(load_model=False)



    prop = AtomicProposition(
        id="P1",
        actor_claim="User",
        action_verb="click",
        target_object="button",
        evidence_spans=["S1"]
    )
    verdicts = openjev.verify_propositions([prop], mock_span_registry)
    assert verdicts["P1"].verdict == GroundingVerdict.SUPPORTED
    assert verdicts["P1"].is_verified is True
    assert "openjev" in verdicts["P1"].provider


def test_factory_provider_resolution():
    """Verifies get_system1_verifier correctly resolves requested provider classes."""
    v_jev = get_system1_verifier("jev")
    assert isinstance(v_jev, JevVerifier)

    v_laya = get_system1_verifier("laya")
    assert isinstance(v_laya, LayaVerifier)

    v_openjev = get_system1_verifier("openjev")
    assert isinstance(v_openjev, OpenJevVerifier)

    with pytest.raises(ValueError, match="Unsupported SYSTEM1_PROVIDER"):
        get_system1_verifier("unknown_provider")


def test_laya_verdict_backwards_compatibility():
    """Verifies LayaVerdict is an exact alias/subclass of System1Verdict."""
    verdict = System1Verdict(
        proposition_id="P_COMPAT",
        verdict=GroundingVerdict.SUPPORTED,
        actor_grounded=True,
        action_entailed=True,
        is_verified=True
    )
    assert isinstance(verdict, LayaVerdict)
    assert isinstance(verdict, System1Verdict)
