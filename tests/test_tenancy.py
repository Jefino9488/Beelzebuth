import pytest
import uuid
from injester.domain.models import UserRole, OrgStatus
from injester.domain.auth import SecurityContext, AccessDeniedError, verify_password
from injester.infrastructure.db import TenantRepository

def test_four_identities_and_tenant_isolation(db_session, superadmin_ctx):
    repo = TenantRepository(db_session)

    # 1. Developer / Super Admin onboards Indian Bank
    org_name = f"Indian Bank {uuid.uuid4().hex[:6]}"
    org_indian_bank = repo.create_organisation(superadmin_ctx, name=org_name)
    assert org_indian_bank.id is not None
    assert org_indian_bank.status == OrgStatus.APPROVED

    # Onboard second client org: Acme Corp
    org_acme = repo.create_organisation(superadmin_ctx, name=f"Acme Corp {uuid.uuid4().hex[:6]}")

    # 2. Assign Client Super Admin for Indian Bank
    ca_user = repo.create_client_admin(
        superadmin_ctx,
        org_id=org_indian_bank.id,
        email=f"admin_{uuid.uuid4().hex[:6]}@indianbank.com",
        password="BankAdminPassword2026!"
    )
    assert ca_user.role == UserRole.CLIENT_ADMIN
    assert ca_user.organisation_id == org_indian_bank.id

    ca_ctx = SecurityContext(
        user_id=ca_user.id,
        email=ca_user.email,
        role=ca_user.role,
        organisation_id=ca_user.organisation_id
    )

    # 3. Client Admin provisions an Employee in Indian Bank
    emp_user_1 = repo.create_employee(
        ca_ctx,
        org_id=org_indian_bank.id,
        email=f"emp1_{uuid.uuid4().hex[:6]}@indianbank.com",
        password="EmpPassword1!"
    )
    emp_ctx_1 = SecurityContext(
        user_id=emp_user_1.id,
        email=emp_user_1.email,
        role=emp_user_1.role,
        organisation_id=emp_user_1.organisation_id
    )

    # Client Admin provisions Employee 2 in Indian Bank
    emp_user_2 = repo.create_employee(
        ca_ctx,
        org_id=org_indian_bank.id,
        email=f"emp2_{uuid.uuid4().hex[:6]}@indianbank.com",
        password="EmpPassword2!"
    )
    emp_ctx_2 = SecurityContext(
        user_id=emp_user_2.id,
        email=emp_user_2.email,
        role=emp_user_2.role,
        organisation_id=emp_user_2.organisation_id
    )

    # Provision user for Acme Corp
    acme_admin = repo.create_client_admin(
        superadmin_ctx,
        org_id=org_acme.id,
        email=f"admin_{uuid.uuid4().hex[:6]}@acme.com",
        password="AcmePassword2026!"
    )
    acme_ctx = SecurityContext(
        user_id=acme_admin.id,
        email=acme_admin.email,
        role=acme_admin.role,
        organisation_id=acme_admin.organisation_id
    )

    # 4. Folder creation & subfolder hierarchy
    root_folder = repo.create_folder(ca_ctx, name="Policies")
    sub_folder = repo.create_folder(ca_ctx, name="IT Security", parent_folder_id=root_folder.id)
    assert sub_folder.parent_folder_id == root_folder.id

    # 5. Employee 1 uploads a file into Indian Bank
    content = b"Indian Bank Confidential Security Policy"
    file_record, version_1 = repo.upload_file(
        sec_ctx=emp_ctx_1,
        filename="Security_Policy.pdf",
        content_bytes=content,
        folder_id=sub_folder.id
    )
    assert file_record.organisation_id == org_indian_bank.id
    assert file_record.created_by_user_id == emp_user_1.id
    assert version_1.version_number == 1

    # Employee 1 uploads version 2 of the file
    new_content = b"Indian Bank Confidential Security Policy v2 with updates"
    _, version_2 = repo.upload_file(
        sec_ctx=emp_ctx_1,
        filename="Security_Policy.pdf",
        content_bytes=new_content,
        existing_file_id=file_record.id
    )
    assert version_2.version_number == 2
    assert version_2.file_hash != version_1.file_hash

    # 6. VERIFY TENANT & ROLE PERMISSIONS AT DATABASE LAYER

    # (a) Client Admin can see ALL organisation files (including Employee 1's)
    ca_files = repo.list_files(ca_ctx)
    assert any(f.id == file_record.id for f in ca_files)
    retrieved_by_ca = repo.get_file(ca_ctx, file_record.id)
    assert retrieved_by_ca.id == file_record.id

    # (b) Employee 1 can see their own file
    emp1_files = repo.list_files(emp_ctx_1)
    assert any(f.id == file_record.id for f in emp1_files)

    # (c) Employee 2 CANNOT see Employee 1's file
    emp2_files = repo.list_files(emp_ctx_2)
    assert not any(f.id == file_record.id for f in emp2_files)
    with pytest.raises(AccessDeniedError):
        repo.get_file(emp_ctx_2, file_record.id)

    # (d) Acme Admin CANNOT see or access Indian Bank's file (strict cross-tenant barrier)
    acme_files = repo.list_files(acme_ctx)
    assert not any(f.id == file_record.id for f in acme_files)
    with pytest.raises(AccessDeniedError):
        repo.get_file(acme_ctx, file_record.id)

    # (e) Super Admin has platform-wide visibility
    super_files = repo.list_files(superadmin_ctx)
    assert any(f.id == file_record.id for f in super_files)
