"""Skill normalization and extraction.

A small curated taxonomy keeps matching deterministic, cheap and explainable.
Each canonical skill maps to aliases; extraction scans text with word-boundary
regexes so "Go" doesn't match "Google" and "C" doesn't match "CI".
"""

from __future__ import annotations

import re
from functools import lru_cache

# canonical -> (category, aliases)
TAXONOMY: dict[str, tuple[str, list[str]]] = {
    # languages
    "python": ("language", ["python", "python3"]),
    "java": ("language", ["java"]),
    "javascript": ("language", ["javascript", "js", "ecmascript"]),
    "typescript": ("language", ["typescript", "ts"]),
    "go": ("language", ["golang", "go lang"]),
    "rust": ("language", ["rust"]),
    "c++": ("language", ["c\\+\\+", "cpp"]),
    "c": ("language", ["c programming", "ansi c"]),
    "c#": ("language", ["c#", "csharp", "\\.net"]),
    "kotlin": ("language", ["kotlin"]),
    "swift": ("language", ["swift"]),
    "scala": ("language", ["scala"]),
    "ruby": ("language", ["ruby"]),
    "php": ("language", ["php"]),
    "sql": ("language", ["sql"]),
    "r": ("language", ["r programming", "rstudio"]),
    "bash": ("language", ["bash", "shell scripting"]),
    # web / backend
    "react": ("frontend", ["react", "react\\.js", "reactjs"]),
    "next.js": ("frontend", ["next\\.js", "nextjs"]),
    "vue": ("frontend", ["vue", "vue\\.js", "vuejs"]),
    "angular": ("frontend", ["angular"]),
    "html/css": ("frontend", ["html", "css", "tailwind"]),
    "node.js": ("backend", ["node\\.js", "nodejs", "node"]),
    "express": ("backend", ["express\\.js", "expressjs"]),
    "django": ("backend", ["django"]),
    "flask": ("backend", ["flask"]),
    "fastapi": ("backend", ["fastapi"]),
    "spring": ("backend", ["spring boot", "spring framework"]),
    "graphql": ("backend", ["graphql"]),
    "rest apis": ("backend", ["restful", "rest apis?"]),
    "grpc": ("backend", ["grpc"]),
    "microservices": ("backend", ["microservices", "microservice"]),
    "distributed systems": ("backend", ["distributed systems", "distributed system"]),
    # data
    "postgresql": ("data", ["postgres", "postgresql"]),
    "mysql": ("data", ["mysql"]),
    "mongodb": ("data", ["mongodb", "mongo"]),
    "redis": ("data", ["redis"]),
    "kafka": ("data", ["kafka"]),
    "spark": ("data", ["spark", "pyspark"]),
    "airflow": ("data", ["airflow"]),
    "elasticsearch": ("data", ["elasticsearch", "opensearch"]),
    "snowflake": ("data", ["snowflake"]),
    "pandas": ("data", ["pandas"]),
    "numpy": ("data", ["numpy"]),
    # cloud / infra
    "aws": ("cloud", ["aws", "amazon web services", "ec2", "s3", "lambda"]),
    "gcp": ("cloud", ["gcp", "google cloud"]),
    "azure": ("cloud", ["azure"]),
    "docker": ("infra", ["docker", "containers"]),
    "kubernetes": ("infra", ["kubernetes", "k8s"]),
    "terraform": ("infra", ["terraform"]),
    "ci/cd": ("infra", ["ci/cd", "ci cd", "github actions", "jenkins", "continuous integration"]),
    "linux": ("infra", ["linux", "unix"]),
    "git": ("infra", ["git", "github", "gitlab"]),
    # ML / AI
    "machine learning": ("ml", ["machine learning", "ml"]),
    "deep learning": ("ml", ["deep learning", "neural networks?"]),
    "pytorch": ("ml", ["pytorch", "torch"]),
    "tensorflow": ("ml", ["tensorflow", "keras"]),
    "scikit-learn": ("ml", ["scikit-learn", "sklearn"]),
    "nlp": ("ml", ["nlp", "natural language processing"]),
    "computer vision": ("ml", ["computer vision", "opencv"]),
    "llms": ("ml", ["llms?", "large language models?", "gpt", "transformers?"]),
    "rag": ("ml", ["rag", "retrieval[- ]augmented generation", "vector databases?", "embeddings"]),
    "mlops": ("ml", ["mlops", "model deployment", "model serving"]),
    "reinforcement learning": ("ml", ["reinforcement learning", "rl"]),
    "statistics": ("ml", ["statistics", "statistical"]),
    # mobile
    "android": ("mobile", ["android"]),
    "ios": ("mobile", ["ios"]),
    "react native": ("mobile", ["react native"]),
    # fundamentals
    "data structures & algorithms": ("cs", ["data structures", "algorithms"]),
    "system design": ("cs", ["system design"]),
    "object-oriented design": ("cs", ["object[- ]oriented", "oop"]),
    "testing": ("cs", ["unit testing", "pytest", "jest", "test automation", "tdd"]),
}

# Aliases that are ambiguous in prose; only matched case-sensitively.
_CASE_SENSITIVE = {"go": r"\bGo\b", "r": r"\bR\b", "c": r"\bC\b(?![+#])", "rl": r"\bRL\b", "ml": r"\bML\b"}


@lru_cache
def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    for canonical, (_, aliases) in TAXONOMY.items():
        parts = [a for a in aliases if a not in ("ml", "rl")]
        if parts:
            out.append((canonical, re.compile(r"(?<![\w+#.])(?:" + "|".join(parts) + r")(?![\w+#])", re.I)))
    for key, pat in _CASE_SENSITIVE.items():
        canonical = {"rl": "reinforcement learning", "ml": "machine learning"}.get(key, key)
        out.append((canonical, re.compile(pat)))
    return out


def normalize_skill(name: str) -> str:
    """Map a free-text skill to its canonical name (or a cleaned lowercase form)."""
    s = name.strip()
    if not s:
        return ""
    for canonical, pat in _patterns():
        m = pat.fullmatch(s) or pat.fullmatch(s.lower())
        if m:
            return canonical
    return re.sub(r"\s+", " ", s.lower())


def normalize_skills(names: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for n in names:
        c = normalize_skill(n)
        if c:
            seen.setdefault(c, None)
    return list(seen)


@lru_cache
def _combined() -> tuple[re.Pattern[str], list[tuple[str, re.Pattern[str]]]]:
    """One alternation over every case-insensitive alias (a single scan of the text),
    plus the few case-sensitive patterns that must stay separate."""
    aliases = [a for _, (_, al) in TAXONOMY.items() for a in al if a not in ("ml", "rl")]
    aliases.sort(key=len, reverse=True)  # prefer the longest alias at a position
    combined = re.compile(r"(?<![\w+#.])(?:" + "|".join(aliases) + r")(?![\w+#])", re.I)
    case_sensitive = [
        ({"rl": "reinforcement learning", "ml": "machine learning"}.get(k, k), re.compile(p))
        for k, p in _CASE_SENSITIVE.items()
    ]
    return combined, case_sensitive


@lru_cache(maxsize=2048)
def _canonical_for_match(token: str) -> str | None:
    for canonical, pat in _patterns():
        if pat.fullmatch(token):
            return canonical
    return None


@lru_cache(maxsize=8192)
def _extract(text: str) -> tuple[str, ...]:
    combined, case_sensitive = _combined()
    found = {c for m in combined.finditer(text) if (c := _canonical_for_match(m.group(0).lower()))}
    found |= {c for c, pat in case_sensitive if pat.search(text)}
    order = list(TAXONOMY)
    return tuple(sorted(found, key=order.index))


def extract_skills(text: str) -> list[str]:
    """Return canonical skills mentioned in text, in taxonomy order (cached per text)."""
    return list(_extract(text or ""))


def category(skill: str) -> str:
    return TAXONOMY.get(skill, ("other", []))[0]
