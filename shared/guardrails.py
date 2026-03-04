import logging
from shared.config import EVIDENCE_MIN_LEN, CONFIDENCE_FLOOR  # unified config import

# A list of keywords and phrases that may indicate customer vulnerability.
VULNERABILITY_LEXICON = [
    # Financial Hardship
    "hardship", "can't pay", "cannot pay", "struggling", "unemployed", "job loss",
    "financial difficulty", "debt", "bankruptcy", "foreclosure",
    # Health & Personal Distress
    "sick", "illness", "hospital", "medical", "bereavement", "death", "passed away",
    "divorce", "mental health", "distress", "crisis",
    # Age & Cognitive Vulnerability
    "confused", "pensioner", "elderly", "forgetting", "scam", "scammed"
]

def detect_vulnerability(text: str) -> (bool, list[str]):
    """
    Detects potential customer vulnerability by searching for keywords in text.
    Returns a tuple of (bool: is_vulnerable, list: found_keywords).
    """
    found_keywords = []
    if not isinstance(text, str):
        return False, found_keywords

    lower_text = text.lower()
    for keyword in VULNERABILITY_LEXICON:
        if keyword in lower_text:
            found_keywords.append(keyword)
    
    is_vulnerable = len(found_keywords) > 0
    if is_vulnerable:
        logging.warning(f"Vulnerability Guardrail: Detected potential vulnerability. Keywords found: {found_keywords}")

    return is_vulnerable, found_keywords

def substring_evidence_guard(evidence: str, min_len: int = EVIDENCE_MIN_LEN):
    # uses config default unless explicitly overridden
    return isinstance(evidence, str) and len(evidence.strip()) >= min_len

def enforce_confidence_floors(hits, floor: float = CONFIDENCE_FLOOR):
    # uses config default unless explicitly overridden
    return [h for h in hits if float(h.get("confidence", 0)) >= floor]