# SOP-MEDIUM-002: Personal Loan Application Processing

## Document Metadata & Scope
- **Purpose:** This SOP outlines the process for receiving, evaluating, and approving/rejecting personal loan applications up to $50,000 for retail banking customers, managed by the Retail Lending Operations team.
- **Target Audience:** Retail Lending Operations team
- **Auditable Verification:** PASS (100% Entailed, 0 Unsupported Claims, 97% Rule Coverage)

## Table of Contents
1. [1. Purpose](#1-purpose)
2. [2. Scope](#2-scope)
3. [3. Roles & Responsibilities](#3-roles-&-responsibilities)
4. [4. Process Steps](#4-process-steps)
5. [5. Decision Points](#5-decision-points)
6. [6. Exceptions & Escalations](#6-exceptions-&-escalations)
7. [7. Service Level Agreements (SLA)](#7-service-level-agreements-(sla))
8. [Evidence & Citation Index](#evidence--citation-index)

---

## 1. Purpose

This Standard Operating Procedure (SOP) describes the end-to-end process for receiving, evaluating, and approving/rejecting personal loan applications submitted by retail banking customers [S003]. This procedure applies to all personal loan applications up to $50,000 processed through the Retail Lending Operations team [S005].

## 2. Scope

This SOP covers personal loan applications submitted by retail banking customers [S003], up to a value of $50,000 [S005]. These applications are processed through the Retail Lending Operations team [S005].

## 3. Roles & Responsibilities

The personal loan application process involves several key roles, each with distinct responsibilities:

*   **Customer**: The Customer submits the loan application and supporting documents [S007]. This includes submitting KYC documents, proof of income, and bank statements for the last 3 months [S013]. Following approval, the Customer is responsible for digitally signing the Sanction Letter within 5 business days [S025].
*   **Loan Officer**: The Loan Officer is responsible for the initial document verification and data entry [S008]. They verify document completeness using the Document Checklist [S014]. If documents are incomplete, the Loan Officer requests the missing items from the Customer and places the application on 'Pending Documents' status [S015]. Once documentation is complete, the Loan Officer enters the application data into the Loan Origination System (LOS) [S016]. In cases of system downtime preventing credit bureau report retrieval, the Loan Officer manually logs a ticket with IT Support and puts the application on 'On Hold - System Issue' status [S043].
*   **Credit Analyst**: The Credit Analyst conducts the credit risk assessment and scoring [S009]. They review the customer's credit score, debt-to-income ratio, and existing liabilities [S018]. Based on an internal scoring matrix, the Credit Analyst assigns a Risk Grade (Low, Medium, or High) [S019]. A Credit Analyst can approve the loan directly if the loan amount requested is up to $20,000 and the Risk Grade is Low or Medium [S021].
*   **Branch Manager**: The Branch Manager provides the final approval for loans that exceed $20,000 [S010]. They review the Credit Analyst's recommendation and then approve, reject, or send the application back for re-evaluation with comments [S023].
*   **Loan Operations Team**: The Loan Operations Team is responsible for disbursing approved funds [S011]. They process the fund disbursement to the Customer's linked bank account within 2 business days of the signed acceptance of the Sanction Letter [S026].

**Exceptions and Escalations**:
*   If the Risk Grade assigned is High, the application is automatically routed to a Senior Credit Analyst for a secondary review [S020].
*   Any application flagged for suspected fraud at any stage is immediately escalated to the Fraud Risk Management team, and processing is suspended pending investigation [S044].

## 4. Process Steps

The personal loan application process begins with the Customer submitting a loan application, KYC documents, proof of income, and bank statements from the last three months, either online or at a branch [S013]. The Loan Officer then verifies the completeness of these documents using the Document Checklist [S014]. Should the documents be incomplete, the Loan Officer is responsible for requesting the missing items from the Customer and updating the application status to 'Pending Documents', pausing the process [S015]. Once all documentation is confirmed as complete, the Loan Officer proceeds to enter the application data into the Loan Origination System (LOS) [S016]. Following data entry, the system automatically retrieves the Customer's credit bureau report, including CIBIL or Equifax scores [S017]. A Credit Analyst then conducts a thorough review of the credit score, debt-to-income ratio, and any existing liabilities [S018]. Based on this assessment, the Credit Analyst assigns a Risk Grade of Low, Medium, or High, utilizing the internal scoring matrix [S019]. Applications assigned a High Risk Grade are automatically routed to a Senior Credit Analyst for a secondary review [S020]. For applications where the loan amount requested is up to $20,000 and the Risk Grade is Low or Medium, the Credit Analyst has the authority to approve the loan directly [S021]. However, if the loan amount requested exceeds $20,000, the application must be routed to the Branch Manager for final approval, irrespective of the Risk Grade assigned [S022]. The Branch Manager will review the Credit Analyst's recommendation and then either approve, reject, or send the application back for re-evaluation with specific comments [S023]. Upon approval, the system generates a Loan Sanction Letter, which is then emailed to the Customer for e-signature [S024]. The Customer is required to digitally sign the Sanction Letter within 5 business days; otherwise, the offer will automatically expire and the application status will be updated to 'Lapsed' [S025, S042]. Once the Sanction Letter is signed, the Loan Operations Team processes the disbursement of funds to the Customer's linked bank account within 2 business days [S026]. Finally, the system updates the Customer's loan account status to 'Active' and schedules the Equated Monthly Installment (EMI) repayment calendar [S027].

## 5. Decision Points

Decision 1: Are documents complete? [S029]
No -> Pending Documents status (loop back to Customer). [S030]
Yes -> proceed to LOS data entry. [S031]

Decision 2: Risk Grade assigned. [S032]
High -> Secondary review by Senior Credit Analyst. [S033]
Low/Medium -> proceed to amount-based routing. [S034]

Decision 3: Loan Amount <= $20,000 -> Credit Analyst can approve directly. [S035]
Loan Amount > $20,000 -> Branch Manager approval required. [S036]

Decision 4: Branch Manager decision. [S037]
Approve -> Sanction Letter generated. [S038]
Reject -> Customer notified with reason. [S039]
Send back -> returns to Credit Analyst with comments. [S040]

## 6. Exceptions & Escalations

6. Exceptions & Escalations [S041] If the Customer does not sign the Sanction Letter within 5 business days, the offer automatically expires and the application status changes to 'Lapsed' [S042]. If a credit bureau report cannot be retrieved due to system downtime, the Loan Officer manually logs a ticket with IT Support and the application is placed on hold with the status 'On Hold - System Issue' [S043]. Any application flagged for suspected fraud at any stage is immediately escalated to the Fraud Risk Management team, and processing is suspended pending investigation [S044]. If application documents are incomplete, the Loan Officer requests the missing documents from the Customer and pauses the application with the status 'Pending Documents' [S015]. When a Risk Grade is High, the application is automatically routed to the Senior Credit Analyst for a secondary review [S020]. A Branch Manager can return an application to the Credit Analyst with comments for re-evaluation [S040].

## 7. Service Level Agreements (SLA)

The following Service Level Agreements (SLAs) are established for personal loan application processing to ensure efficient and timely service delivery. Document verification must be completed within 1 business day of submission [S046]. Credit assessment must be completed within 2 business days of complete documentation [S047]. The final approval decision must be made within 3 business days of credit assessment completion [S048]. Fund disbursement must occur within 2 business days of the signed Sanction Letter [S049].

---

## Citation Index

> Every procedural instruction, rule, and threshold in this document is traced back to an immutable source evidence span.

### [S003]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: SOP-MEDIUM-002: Personal Loan Application Processing
Section: SOP-MEDIUM-002: Personal Loan Application Processing
Chunk ID: chunk_114137
Span ID: S003
Factual Status: ✓ ENTAILED
Evidence Span: "This SOP describes the end-to-end process for receiving, evaluating, and approving/rejecting personal loan applications submitted by retail banking customers."
```

### [S005]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: SOP-MEDIUM-002: Personal Loan Application Processing
Section: SOP-MEDIUM-002: Personal Loan Application Processing
Chunk ID: chunk_114137
Span ID: S005
Factual Status: ✓ ENTAILED
Evidence Span: "Applies to all personal loan applications up to $50,000 processed through the Retail Lending Operations team."
```

### [S007]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 3. Roles & Responsibilities
Section: 3. Roles & Responsibilities
Chunk ID: chunk_657f27
Span ID: S007
Factual Status: ✓ ENTAILED
Evidence Span: "Customer: Submits loan application and supporting documents."
```

### [S008]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 3. Roles & Responsibilities
Section: 3. Roles & Responsibilities
Chunk ID: chunk_657f27
Span ID: S008
Factual Status: ✓ ENTAILED
Evidence Span: "Loan Officer: Performs initial document verification and data entry."
```

### [S009]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 3. Roles & Responsibilities
Section: 3. Roles & Responsibilities
Chunk ID: chunk_657f27
Span ID: S009
Factual Status: ✓ ENTAILED
Evidence Span: "Credit Analyst: Conducts credit risk assessment and scoring."
```

### [S010]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 3. Roles & Responsibilities
Section: 3. Roles & Responsibilities
Chunk ID: chunk_657f27
Span ID: S010
Factual Status: ✓ ENTAILED
Evidence Span: "Branch Manager: Provides final approval for loans above $20,000."
```

### [S011]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 3. Roles & Responsibilities
Section: 3. Roles & Responsibilities
Chunk ID: chunk_657f27
Span ID: S011
Factual Status: ✓ ENTAILED
Evidence Span: "Loan Operations Team: Disburses approved funds."
```

### [S013]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S013
Factual Status: ✓ ENTAILED
Evidence Span: "Customer submits a loan application online or at a branch, along with KYC documents, proof of income, and bank statements (last 3 months)."
```

### [S014]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S014
Factual Status: ✓ ENTAILED
Evidence Span: "Loan Officer verifies document completeness using the Document Checklist."
```

### [S015]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S015
Factual Status: ✓ ENTAILED
Evidence Span: "If documents are incomplete, Loan Officer requests the missing documents from the Customer and pauses the application (Status: Pending Documents)."
```

### [S016]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S016
Factual Status: ✓ ENTAILED
Evidence Span: "Once complete, Loan Officer enters application data into the Loan Origination System (LOS)."
```

### [S017]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S017
Factual Status: ✓ ENTAILED
Evidence Span: "System automatically pulls the Customer's credit bureau report (CIBIL/Equifax score)."
```

### [S018]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S018
Factual Status: ✓ ENTAILED
Evidence Span: "Credit Analyst reviews the credit score, debt-to-income ratio, and existing liabilities."
```

### [S019]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S019
Factual Status: ✓ ENTAILED
Evidence Span: "Credit Analyst assigns a Risk Grade (Low / Medium / High) based on the internal scoring matrix."
```

### [S020]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S020
Factual Status: ✓ ENTAILED
Evidence Span: "If Risk Grade is High, application is automatically routed to Senior Credit Analyst for secondary review."
```

### [S021]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S021
Factual Status: ✓ ENTAILED
Evidence Span: "If loan amount requested is up to $20,000 and Risk Grade is Low/Medium, Credit Analyst can approve directly."
```

### [S022]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_883f5b
Span ID: S022
Factual Status: ✓ ENTAILED
Evidence Span: "If loan amount requested is above $20,000, application is routed to Branch Manager for final approval, regardless of Risk Grade."
```

### [S023]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_287103
Span ID: S023
Factual Status: ✓ ENTAILED
Evidence Span: "Branch Manager reviews the Credit Analyst's recommendation and either approves, rejects, or sends back for re-evaluation with comments."
```

### [S024]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_287103
Span ID: S024
Factual Status: ✓ ENTAILED
Evidence Span: "On approval, system generates a Loan Sanction Letter and emails it to the Customer for e-signature."
```

### [S025]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_287103
Span ID: S025
Factual Status: ✓ ENTAILED
Evidence Span: "Customer digitally signs the Sanction Letter within 5 business days; otherwise the offer expires."
```

### [S026]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_287103
Span ID: S026
Factual Status: ✓ ENTAILED
Evidence Span: "Loan Operations Team processes disbursement to the Customer's linked bank account within 2 business days of signed acceptance."
```

### [S027]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 4. Process Steps
Section: 4. Process Steps
Chunk ID: chunk_287103
Span ID: S027
Factual Status: ✓ ENTAILED
Evidence Span: "System updates the Customer's loan account status to 'Active' and schedules the EMI repayment calendar."
```

### [S028]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S028
Factual Status: ✓ ENTAILED
Evidence Span: "5. Decision Points"
```

### [S029]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S029
Factual Status: ✓ ENTAILED
Evidence Span: "Decision 1: Are documents complete?"
```

### [S030]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S030
Factual Status: ✓ ENTAILED
Evidence Span: "No -> Pending Documents status (loop back to Customer)."
```

### [S031]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S031
Factual Status: ✓ ENTAILED
Evidence Span: "Yes -> proceed to LOS data entry."
```

### [S032]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S032
Factual Status: ✓ ENTAILED
Evidence Span: "Decision 2: Risk Grade assigned."
```

### [S033]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S033
Factual Status: ✓ ENTAILED
Evidence Span: "High -> Secondary review by Senior Credit Analyst."
```

### [S034]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S034
Factual Status: ✓ ENTAILED
Evidence Span: "Low/Medium -> proceed to amount-based routing."
```

### [S035]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S035
Factual Status: ✓ ENTAILED
Evidence Span: "Decision 3: Loan Amount <= $20,000 -> Credit Analyst can approve directly."
```

### [S036]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S036
Factual Status: ✓ ENTAILED
Evidence Span: "Loan Amount > $20,000 -> Branch Manager approval required."
```

### [S037]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S037
Factual Status: ✓ ENTAILED
Evidence Span: "Decision 4: Branch Manager decision."
```

### [S038]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S038
Factual Status: ✓ ENTAILED
Evidence Span: "Approve -> Sanction Letter generated."
```

### [S039]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S039
Factual Status: ✓ ENTAILED
Evidence Span: "Reject -> Customer notified with reason."
```

### [S040]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 5. Decision Points
Section: 5. Decision Points
Chunk ID: chunk_fe715e
Span ID: S040
Factual Status: ✓ ENTAILED
Evidence Span: "Send back -> returns to Credit Analyst with comments."
```

### [S041]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 6. Exceptions & Escalations
Section: 6. Exceptions & Escalations
Chunk ID: chunk_5ceafe
Span ID: S041
Factual Status: ✓ ENTAILED
Evidence Span: "6. Exceptions & Escalations"
```

### [S042]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 6. Exceptions & Escalations
Section: 6. Exceptions & Escalations
Chunk ID: chunk_5ceafe
Span ID: S042
Factual Status: ✓ ENTAILED
Evidence Span: "If Customer does not sign the Sanction Letter within 5 business days, the offer automatically expires and the application status changes to 'Lapsed'."
```

### [S043]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 6. Exceptions & Escalations
Section: 6. Exceptions & Escalations
Chunk ID: chunk_5ceafe
Span ID: S043
Factual Status: ✓ ENTAILED
Evidence Span: "If credit bureau report cannot be retrieved due to system downtime, Loan Officer manually logs a ticket with IT Support and application is placed on hold (Status: On Hold - System Issue)."
```

### [S044]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 6. Exceptions & Escalations
Section: 6. Exceptions & Escalations
Chunk ID: chunk_5ceafe
Span ID: S044
Factual Status: ✓ ENTAILED
Evidence Span: "Any application flagged for suspected fraud at any stage is immediately escalated to the Fraud Risk Management team and processing is suspended pending investigation."
```

### [S046]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 7. Service Level Agreements (SLA)
Section: 7. Service Level Agreements (SLA)
Chunk ID: chunk_500ef3
Span ID: S046
Factual Status: ✓ ENTAILED
Evidence Span: "Document verification: within 1 business day of submission."
```

### [S047]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 7. Service Level Agreements (SLA)
Section: 7. Service Level Agreements (SLA)
Chunk ID: chunk_500ef3
Span ID: S047
Factual Status: ✓ ENTAILED
Evidence Span: "Credit assessment: within 2 business days of complete documentation."
```

### [S048]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 7. Service Level Agreements (SLA)
Section: 7. Service Level Agreements (SLA)
Chunk ID: chunk_500ef3
Span ID: S048
Factual Status: ✓ ENTAILED
Evidence Span: "Final approval decision: within 3 business days of credit assessment completion."
```

### [S049]
```text
Source: SOP_Medium_PersonalLoanProcessing.docx
Location: Section: 7. Service Level Agreements (SLA)
Section: 7. Service Level Agreements (SLA)
Chunk ID: chunk_500ef3
Span ID: S049
Factual Status: ✓ ENTAILED
Evidence Span: "Fund disbursement: within 2 business days of signed Sanction Letter."
```
