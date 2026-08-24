import re


REDACTION_PATTERNS = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已脱敏]"),
    (
        re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE),
        "[邮箱已脱敏]",
    ),
    (
        re.compile(r"(?<!\d)\d{6}(?:18|19|20)\d{2}[01]\d[0-3]\d\d{3}[\dXx](?!\d)"),
        "[证件号已脱敏]",
    ),
]


def redact_resume_text(text, candidate_name=""):
    redacted = text or ""
    if candidate_name:
        redacted = redacted.replace(candidate_name, "[姓名已脱敏]")
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted

