
"""
schema_ref_extractor.py

Extract schemaRef URIs from a loaded Arelle model and identify
the US-GAAP taxonomy year declared by the filing.
"""

import logging
import re
from dataclasses import dataclass

from xbrl_utils import US_GAAP_URI_PATTERN

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaxonomyInfo:
    """Immutable record of a filing's declared taxonomies."""
    schema_refs: list[str]
    us_gaap_year: str | None  # e.g., "2024", "2023"
    us_gaap_uri: str | None


def extract_taxonomy_info(model_xbrl) -> TaxonomyInfo:
    """
    Extract schemaRef URIs and identify the US-GAAP taxonomy year.
    
    Arelle resolves all schemaRefs when loading the DTS. We inspect
    the modelDocument.referencesDocument map for schema-type references.
    """
    schema_refs: list[str] = []
    
    # Arelle stores referenced docs in referencesDocument (dict-like)
    # Keys are ModelDocument objects; .type == 2 means XSD schema
    refs = getattr(model_xbrl.modelDocument, "referencesDocument", {})
    for ref_doc in refs.keys():
        uri = getattr(ref_doc, "uri", None)
        if uri is None:
            continue
        
        # Filter to actual schema references (type==2) — not linkbases (type==3)
        doc_type = getattr(ref_doc, "type", None)
        if doc_type != 2:
            continue
        
        schema_refs.append(uri)
    
    # Identify US-GAAP taxonomy year from URI pattern
    # Example: https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd
    us_gaap_uri = None
    us_gaap_year = None
    
    for uri in schema_refs:
        if US_GAAP_URI_PATTERN in uri.lower():
            us_gaap_uri = uri
            # Extract year via regex
            match = re.search(r'us-gaap[/-](\d{4})', uri, re.IGNORECASE)
            if match:
                us_gaap_year = match.group(1)
                logger.info("Detected US-GAAP taxonomy year: %s", us_gaap_year)
            break
    
    # Fallback: when loading an instance doc, modelDocument.referencedNamespaces may be empty.
    # Use model.namespaceDocs which maps namespace URIs to their document objects.
    if us_gaap_year is None:
        ns_docs = getattr(model_xbrl, "namespaceDocs", {})
        for ns_uri in ns_docs:
            ns_lower = ns_uri.lower()
            if US_GAAP_URI_PATTERN in ns_lower:
                us_gaap_uri = ns_uri
                match = re.search(r'us-gaap[/-](\d{4})', ns_uri, re.IGNORECASE)
                if match:
                    us_gaap_year = match.group(1)
                    logger.info("Detected US-GAAP year from namespaceDocs: %s", us_gaap_year)
                break
    
    # Final fallback: walk all loaded documents in the DTS
    if us_gaap_year is None:
        url_docs = getattr(model_xbrl, "urlDocs", {})
        for doc_uri, md in url_docs.items():
            if US_GAAP_URI_PATTERN in doc_uri.lower():
                us_gaap_uri = doc_uri
                match = re.search(r'us-gaap[/-](\d{4})', doc_uri, re.IGNORECASE)
                if match:
                    us_gaap_year = match.group(1)
                    logger.info("Detected US-GAAP year from urlDocs: %s", us_gaap_year)
                break
    
    if us_gaap_year is None:
        logger.warning("Could not detect US-GAAP year")
    
    return TaxonomyInfo(
        schema_refs=schema_refs,
        us_gaap_year=us_gaap_year,
        us_gaap_uri=us_gaap_uri,
    )