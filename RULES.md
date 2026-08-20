# Classification Rules

&gt; One rule per classification category with real APLD examples.
&gt; Every rule references concrete evidence types, not vague language.

---

## MATCHES_STANDARD

**Rule 1:** If a concept's namespace URI contains `fasb.org`, `xbrl.org`, `sec.gov`, or `w3.org`, classify as STANDARD.

**Evidence:** Namespace URI inspection.

**Example:** `us-gaap:LongTermDebt` → `http://fasb.org/us-gaap/2025` → STANDARD.

---

## MATCHES_EXISTING_EXTENSION

**Rule 2:** If a concept name exactly matches a name already in the schema's COMPANY set, classify as MATCHES_EXISTING_EXTENSION.

**Evidence:** Name string equality against schema's known company extensions.

**Example:** If `apld:CornerstoneBankLoanMember` was in v1, it matches in v2.

---

## RELATED_NOT_COMBINABLE

**Rule 3:** If a concept name or label contains any of: `issuancecost`, `discount`, `deferredfinancing`, `premium`, `debtissuance`, `unamortized`, `deferredcost`, `issuance` — classify as NOT_COMBINABLE.

**Evidence:** Keyword match in name or label.

**Example:** `us-gaap:DebtIssuanceCosts` — this is an asset/offset to debt, not a component of total debt principal.

**Rule 4:** If a concept appears as a child in a calc arc with weight &lt; 0 (subtraction), classify as NOT_COMBINABLE.

**Evidence:** Calc arc weight attribute.

**Example:** If `DebtDiscount` has weight -1.0 under `LongTermDebt`, it reduces the total rather than adding to it.

---

## NEW_EXTENSION_RESOLVED

**Rule 5:** If a company concept is the target of a calc arc from a known concept in the schema, classify as RESOLVED.

**Evidence:** `summation-item` arcrole with `from` concept in current schema.

**Example:** `apld:CIMPromissoryNoteMember` is a dimension member of `DebtInstrumentAxis` (known in schema) → RESOLVED.

**Rule 6:** If a company concept is a presentation child of a known concept, classify as RESOLVED.

**Evidence:** `parent-child` arcrole with parent in current schema.

---

## NEW_EXTENSION_UNRESOLVED

**Rule 7:** If none of the above rules apply, classify as UNRESOLVED. Do not guess.

**Evidence:** Absence of name match, namespace match, calc link, dimension link, presentation link, or exclusion keyword.

**Example:** A company concept named `apld:MiscellaneousFinancingObligation` with no arcs to known concepts and no exclusion keywords → UNRESOLVED.