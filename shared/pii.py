import re

EMAIL_RE = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
PHONE_RE = re.compile(r'\b(?:\+?\d{1,3})?[-.\s]?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}\b')

def scrub_text(s: str) -> str:
    s = EMAIL_RE.sub("[email]", s or "")
    s = PHONE_RE.sub("[phone]", s)
    return s