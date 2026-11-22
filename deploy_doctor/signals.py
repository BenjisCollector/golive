"""Turn raw deployment logs and config into structured signals.

Every diagnoser downstream works from these signals, never from free text,
so a diagnosis can always be traced back to the exact log line that caused it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HTTP_RE = re.compile(r"\b(?:HTTP|status(?:_code)?)[ /=:]*([1-5]\d\d)\b", re.I)
AADSTS_RE = re.compile(r"\bAADSTS(\d{5,7})\b")
RETRY_AFTER_RE = re.compile(r"retry[-_ ]after[\"']?\s*[:=]\s*(\d+)", re.I)
TOKENS_RE = re.compile(r"(\d{3,7})\s*tokens?", re.I)


@dataclass
class Signals:
    http_codes: list[int] = field(default_factory=list)
    aadsts: list[str] = field(default_factory=list)
    retry_after_s: int | None = None
    keywords: set[str] = field(default_factory=set)
    evidence: dict[str, str] = field(default_factory=dict)  # keyword -> first log line
    token_counts: list[int] = field(default_factory=list)
    config: dict = field(default_factory=dict)


# keyword -> regex. Order does not matter; every match is kept with its line.
KEYWORDS = {
    "invalid_audience": r"invalid audience|aud(ience)? claim|InvalidAudience",
    "missing_scope": r"insufficient (scope|privileges)|scope[s]? (is |are )?missing|Authorization_RequestDenied",
    "expired_token": r"token (is )?expired|ExpiredToken|lifetime validation failed",
    "consent_required": r"consent_required|admin consent|has not consented",
    "rate_limited": r"rate ?limit|too many requests|quota exceeded|TPM limit|RPM limit",
    "context_length": r"context[_ ]length|maximum context|too many tokens|max_tokens",
    "content_filter": r"content[_ ]filter|ResponsibleAIPolicyViolation|blocked by safety",
    "index_not_found": r"index .*not found|IndexNotFound|no such index",
    "dimension_mismatch": r"dimension(s)? mismatch|expected \d+ dimensions|vector dimension",
    "empty_retrieval": r"0 (documents|results|chunks)|no documents retrieved|empty context",
    "timeout": r"timed? ?out|ReadTimeout|deadline exceeded",
    "dns": r"name or service not known|getaddrinfo|NXDOMAIN|could not resolve",
    "private_endpoint": r"public network access is disabled|private endpoint|403 .*network|firewall",
    "deployment_not_found": r"DeploymentNotFound|deployment .*does not exist|model .*not found",
}
KEYWORD_RES = {k: re.compile(v, re.I) for k, v in KEYWORDS.items()}


def extract(logs: str, config: dict | None = None) -> Signals:
    s = Signals(config=dict(config or {}))
    for line in logs.splitlines():
        for m in HTTP_RE.finditer(line):
            s.http_codes.append(int(m.group(1)))
        for m in AADSTS_RE.finditer(line):
            s.aadsts.append(m.group(1))
        m = RETRY_AFTER_RE.search(line)
        if m and s.retry_after_s is None:
            s.retry_after_s = int(m.group(1))
        for m in TOKENS_RE.finditer(line):
            s.token_counts.append(int(m.group(1)))
        for key, rx in KEYWORD_RES.items():
            if rx.search(line):
                s.keywords.add(key)
                s.evidence.setdefault(key, line.strip())
    return s
