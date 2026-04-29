# Structured Finance Department — AI Context Document
# Islamic Bank — Turkey
# Version: 1.0 | For internal AI agent use

---

## 1. Department Overview

The Structured Finance department is a relatively new unit within an Islamic Bank headquartered in Turkey. The bank has historically focused on traditional Islamic lending products (murabaha, leasing, etc.), and this department was established to serve a more sophisticated, deal-intensive segment of the corporate market.

**Mission:** Design, structure, and manage specialized financing products and transactions for large corporate and high-value commercial customers — including bilateral transactions, guaranteed facilities, international referrals, and capital market-linked instruments such as Sukuk and syndicated loans.

**Positioning:** The department operates as a flexible, deal-driven unit. It is not limited to pure lending — it also acts as an arranger, facilitator, or guarantor, connecting customers with international financial institutions when appropriate.

---

## 2. Customer Segments

The bank classifies its business customers (tüzel müşteriler) into four segments by size:

| Segment | Description |
|---|---|
| **Micro** | Smallest size. Not in scope for this department. |
| **Enterprise (KOBİ)** | Small-to-medium businesses. Occasionally in scope. |
| **Commercial** | Mid-size companies. Large commercials are frequently in scope. |
| **Corporate** | Largest companies in Turkey. Primary focus segment. |

**Department focus:** Primarily **Corporate**, with regular inclusion of large **Commercial** customers when deal complexity or size warrants structured financing.

---

## 3. Products

A **Product** is a defined, reusable financing solution that the department offers or facilitates. Products are pre-defined and must exist before any deal can be created for them.

Key characteristics:
- Defines **what type of financing** is offered (e.g., guaranteed loan, sukuk, syndication).
- May involve a **partner institution** (e.g., KT Bank AG, a development bank, an international lender).
- Has **default fields** — attributes required for every deal linked to it (e.g., currency, tenor, minimum size).
- May be **connected to one or more OKRs** — deals under this product contribute to those objectives.
- **A deal cannot be created without a linked product.**

Example products:
- KT Bank AG Loan Facility (EUR, up to 20M)
- International Guaranteed Murabaha
- Sukuk Issuance
- XYZ Bank Syndicated Loan (with department guarantee)

---

## 4. Deals

A **Deal** is a specific transaction between the bank and a customer, structured under a defined product.

**Formula:** Customer + Product = Deal

A deal represents the actual financing event. For example:
- Customer A receives 10 million EUR under the XYZ Bank Loan Facility → this is a deal.
- Customer B issues 20 million USD via KT Bank AG → this is a deal.

Deal details include: deal size, currency, tenor, contact person, status, expected pricing, notes, and linked product.

Deal pipeline: Lead → Proposal → Due Diligence → Closed Won / Closed Lost

A deal feeds OKRs through its linked product.

---

## 5. OKRs (Objectives and Key Results)

**Structure:**
```
Objective
  └── Key Result 1 (Target, Current Value, % Achievement)
  └── Key Result 2 ...
```

- An **Objective** is a qualitative strategic goal.
- A **Key Result** is a measurable outcome with a target value.
- KRs are linked to specific products. Every deal under that product auto-contributes to the KR.
- Calculation method differs per KR: count of deals, sum of deal sizes, geographic/segment-specific targets.
- OKRs may be time-bound (annual, quarterly).

Example:
> **Objective:** Expand structured finance reach in the tourism sector
> **KR1:** 10 companies onboarded under XYZ Guaranteed Product → Current: 3/10 (30%)
> **KR2:** Total deal volume > 50M EUR → Current: 12M EUR (24%)

---

## 6. Projects

A **Project** is internal department work — not a customer deal. Projects track major initiatives, product development, or administrative undertakings.

A project:
- Is owned by a department member
- Has a defined status (Planning, Active, On Hold, Completed)
- Has optional start/end dates and deadlines
- Has its own backlog of work items
- May optionally be connected to an Objective

Example: Developing the Customer Tracker web application with AI agent capabilities.

---

## 7. Backlog and Work Items

The **Backlog** is the operational backbone of the department. Every deal and every project has an associated backlog — an ordered list of work items that must be completed for the deal or project to be considered done.

**Work Item characteristics:**
- Title, description, optional deadline, status (Not Started, In Progress, Done, Blocked)
- May have **prerequisite items** — items that must be completed before this one can start
- May have **sub-items** (child tasks), which can also have their own prerequisites
- Sorting: prerequisites first → deadline → ID

**Backlog completion:** When all work items are Done, the deal or project is complete.

---

## 8. Entity Relationships

```
Customer
  └── Deal (many)
        └── linked to Product (one)
        └── feeds OKR KRs via Product
        └── Backlog → Work Items

Product
  └── linked to OKR KRs (optional)
  └── contains default deal fields

Objective
  └── Key Results (many)
        └── aggregated from linked Deals via Products

Project
  └── Backlog → Work Items
  └── optionally linked to an Objective
```

---

## 9. Entity ID Prefix Scheme

| Prefix | Entity |
|---|---|
| 110xxxx | Product |
| 111xxxx | Product Default Field |
| 210xxxx | Deal |
| 310xxxx | Objective |
| 311xxxx | Key Result |
| 312xxxx | OKR–Product Link |
| 320xxxx | Project |
| 410xxxx | Backlog Work Item |
| 411xxxx | Work Item Sub-Item |
| 412xxxx | Work Item Prerequisite Link |

All entities have: prefixed unique ID, IsActive (TINYINT default 1), created_at, updated_at.

---

## 10. Key Terminology

| Turkish | English |
|---|---|
| Tüzel müşteri | Legal entity / corporate customer |
| Kurumsal | Corporate segment |
| Ticari | Commercial segment |
| Yapılandırılmış finansman | Structured finance |
| OKR | Objectives and Key Results |
| İş kalemi | Work item |
| Birikim listesi | Backlog |
| Ürün | Product |
| Anlaşma / İşlem | Deal |
| Proje | Project |
