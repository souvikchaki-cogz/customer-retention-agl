def substring_evidence_guard(evidence: str, min_len: int = 4):
    return isinstance(evidence, str) and len(evidence.strip()) >= min_len

def enforce_confidence_floors(hits, floor: float = 0.5):
    return [h for h in hits if float(h.get("confidence", 0)) >= floor]