
"""
xbrl_utils.py

Shared constants and helpers for XBRL parsing.

"""

from typing import Final

#  Debt keywords 
DEBT_KEYWORDS: Final[frozenset[str]] = frozenset([
    "debt", "loan", "note", "borrow", "financing", "obligation",
    "convertible", "promissory", "credit facility", "term loan",
    "lease liability", "debt issuance", "unamortized discount",
    "embedded derivative", "capped call", "warrant",
])

#  Namespace classification 
STANDARD_URI_FRAGMENTS: Final[frozenset[str]] = frozenset([
    "fasb.org", "xbrl.org", "sec.gov", "w3.org",
])

COMPANY_URI_FRAGMENTS: Final[frozenset[str]] = frozenset([
    "appliedblockchaininc", "apld", "applieddigital",
])

def classify_namespace(uri: str) -> str:
    uri_lower = uri.lower()
    if any(s in uri_lower for s in STANDARD_URI_FRAGMENTS):
        return "STANDARD"
    if any(s in uri_lower for s in COMPANY_URI_FRAGMENTS):
        return "COMPANY"
    return "OTHER"

#  Standard taxonomy detection 
US_GAAP_URI_PATTERN: Final[str] = "fasb.org/us-gaap"
US_GAAP_DEBT_ROOTS: Final[frozenset[str]] = frozenset([
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "LongTermDebtCurrent",
    "DebtCurrent",
    "ConvertibleDebt",
    "ConvertibleDebtNoncurrent",
    "NotesPayable",
    "LongTermNotesPayable",
    "LinesOfCreditCurrent",
    "LinesOfCreditNoncurrent",
    "FinanceLeaseLiability",
    "FinanceLeaseLiabilityNoncurrent",
    "FinanceLeaseLiabilityCurrent",
    "DebtInstrumentLineItems",
])

#  XBRL Dimensions arcroles 
DIM_ALL: Final[str] = "http://xbrl.org/int/dim/arcrole/all"
DIM_NOT_ALL: Final[str] = "http://xbrl.org/int/dim/arcrole/notAll"
DIM_HYPERCUBE_DIMENSION: Final[str] = "http://xbrl.org/int/dim/arcrole/hypercube-dimension"
DIM_DIMENSION_DOMAIN: Final[str] = "http://xbrl.org/int/dim/arcrole/dimension-domain"
DIM_DOMAIN_MEMBER: Final[str] = "http://xbrl.org/int/dim/arcrole/domain-member"