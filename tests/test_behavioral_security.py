"""
Behavioral Security Matrix & Negative-Path Authorization Tests (BAT-01 through BAT-08).
Enforces strict trust boundaries, resource-level ACLs, epistemic/deontic fidelity, and dev-login gates.
"""

import pytest
import uuid
from fastapi.testclient import TestClient
from injester.domain.models import UserRole, OrgStatus
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.infrastructure.db import TenantRepository
from injester.pipeline import InjesterPipeline
from injester.config import settings
from injester.semantic.schemas import (
    AtomicProposition,
    ModalityType,
    EpistemicStatus,
    GroundingVerdict,
    RawTypedDecisions,
)
from injester.semantic.verifiers.policy import System1ValidationPolicy


def test_bat_03_inaccessible_file_ids_raises_access_denied(db_session, superadmin_ctx):
    """BAT-03: Requesting inaccessible file_ids in digest generation raises AccessDeniedError (no silent subsetting)."""
    repo = TenantRepository(db_session)

    # 1. Setup Org A and Org B
    org_a = repo.create_organisation(superadmin_ctx, name=f"Org A {uuid.uuid4().hex[:6]}")
    repo.approve_organisation(superadmin_ctx, org_a.id)
    org_b = repo.create_organisation(superadmin_ctx, name=f"Org B {uuid.uuid4().hex[:6]}")
    repo.approve_organisation(superadmin_ctx, org_b.id)

    # 2. Provision Employee in Org A
    emp_a = repo.create_employee(
        superadmin_ctx, org_id=org_a.id, email=f"user_a_{uuid.uuid4().hex[:6]}@orga.com", password="Password123!"
    )
    sec_ctx_a = SecurityContext(
        user_id=emp_a.id, email=emp_a.email, role=emp_a.role, organisation_id=org_a.id
    )

    # 3. Upload File in Org A and File in Org B
    file_a, _ = repo.upload_file(sec_ctx_a, filename="doc_a.txt", content_bytes=b"Content A")
    
    emp_b = repo.create_employee(
        superadmin_ctx, org_id=org_b.id, email=f"user_b_{uuid.uuid4().hex[:6]}@orgb.com", password="Password123!"
    )
    sec_ctx_b = SecurityContext(
        user_id=emp_b.id, email=emp_b.email, role=emp_b.role, organisation_id=org_b.id
    )
    file_b, _ = repo.upload_file(sec_ctx_b, filename="doc_b.txt", content_bytes=b"Content B")

    # 4. User A requests [file_a.id, file_b.id]
    pipeline = InjesterPipeline(session=db_session)
    with pytest.raises(AccessDeniedError, match="Inaccessible resources requested"):
        pipeline.generate_digest(
            sec_ctx=sec_ctx_a,
            topic_goal="Digest Generation",
            file_ids=[file_a.id, file_b.id]
        )


def test_bat_06_negative_record_epistemic_inversion():
    """BAT-06: Flagged as negative record inversion when proposition asserts confirmed fact but evidence states absent record."""
    policy = System1ValidationPolicy()

    # Proposition asserts CONFIRMED fact
    prop = AtomicProposition(
        id="P_EPI",
        actor_claim="Auditor",
        action_verb="verify",
        target_object="records",
        modality=ModalityType.MANDATORY,
        epistemic_status=EpistemicStatus.CONFIRMED,
        evidence_spans=["S1"]
    )

    # Verifier classified evidence as ABSENT_RECORD ("unrecorded")
    raw = RawTypedDecisions(
        actor_p=0.95,
        action_p=0.95,
        modality_choice="mandatory",
        epistemic_choice="unrecorded"
    )

    verdict = policy.evaluate(prop, raw)
    assert verdict.is_epistemic_inverted is True
    assert verdict.is_verified is False
    assert verdict.verdict == GroundingVerdict.UNSUPPORTED
    assert any("Negative record inversion" in r for r in verdict.rejection_reasons)


def test_bat_07_deontic_modality_escalation():
    """BAT-07: Flagged as modality escalation when proposition asserts mandatory obligation but evidence is permissive."""
    policy = System1ValidationPolicy()

    # Proposition asserts MANDATORY
    prop = AtomicProposition(
        id="P_MOD",
        actor_claim="Operator",
        action_verb="review",
        target_object="log",
        modality=ModalityType.MANDATORY,
        epistemic_status=EpistemicStatus.CONFIRMED,
        evidence_spans=["S1"]
    )

    # Verifier classified evidence as PERMISSIVE ("may" / "optional")
    raw = RawTypedDecisions(
        actor_p=0.95,
        action_p=0.95,
        modality_choice="permissive",
        epistemic_choice="confirmed"
    )

    verdict = policy.evaluate(prop, raw)
    assert verdict.is_modality_escalated is True
    assert verdict.is_verified is False
    assert verdict.verdict == GroundingVerdict.UNSUPPORTED
    assert any("Deontic escalation" in r for r in verdict.rejection_reasons)


def test_bat_08_credential_login_stays_available_when_dev_login_disabled(monkeypatch):
    """BAT-08: the one-click dev shortcut is gone; credential sign-in must still work."""
    from injester.api.app import app
    client = TestClient(app)

    monkeypatch.setattr(settings, "ENABLE_DEV_LOGIN", False)

    # There is no one-click system-admin shortcut endpoint any more.
    res_shortcut = client.post("/api/auth/system-admin")
    assert res_shortcut.status_code in (404, 405)

    # The credential login path stays available.
    res_login = client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": settings.SUPERADMIN_INITIAL_PASSWORD,
    })
    assert res_login.status_code == 200
