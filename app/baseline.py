"""Keyword RAG baseline (F7): plain keyword retrieval over the Message text, then the LLM.

Retrieval is still keyword matching on the FalkorDB full-text index. The steps:
  1. Split the question into keyword parts. A hyphenated term such as payments-api
     also contributes its parts (payments, api).
  2. Ask the full-text index for a candidate pool (B1_CANDIDATES) with those parts, OR-ed.
  3. Re-rank the pool, without any hand-picked answers:
       a. messages that contain the whole hyphenated term (payments-api) first,
       b. then the number of distinct question parts the message contains,
       c. then the full-text score.
     Keep the top 3.
The LLM then answers only from those 3 snippets, and its citations are normalised.
"""
import re
from pathlib import Path

from app import db, llm, queries
from app.agent import strip_citations

STOPWORDS = {
    "a", "an", "and", "at", "by", "did", "do", "does", "for", "if", "in", "is", "of",
    "on", "or", "since", "the", "to", "what", "who",
}
PROMPT = (Path(__file__).resolve().parent / "prompts" / "baseline.txt").read_text(encoding="utf-8")
TOP_K = 3
HYPHENATED = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+")


def _question_terms(question: str) -> tuple[list[str], list[str]]:
    """Return (parts, hyphenated_terms), both lower-cased, without stopwords."""
    hyphenated = [h.lower() for h in HYPHENATED.findall(question)]
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", question)]
    parts = []
    for w in words:
        if w not in STOPWORDS and w not in parts:
            parts.append(w)
    return parts, hyphenated


def search_terms(question: str) -> str:
    """Full-text query: the parts of the question, OR-joined."""
    parts, _ = _question_terms(question)
    return " | ".join(parts)


def _rerank(question: str, rows: list[dict]) -> list[dict]:
    parts, hyphenated = _question_terms(question)

    def key(row: dict):
        text = row["text"].lower()
        tokens = set(re.findall(r"[a-z0-9]+", text))
        whole = any(term in text for term in hyphenated)
        overlap = sum(1 for p in parts if p in tokens)
        return (whole, overlap, row["score"])

    return sorted(rows, key=key, reverse=True)


def snippets(graph, question: str) -> list[dict]:
    q = search_terms(question)
    if not q:
        return []
    pool = db.read(graph, queries.B1_CANDIDATES, {"q": q})
    ranked = _rerank(question, pool)[:TOP_K]
    return [
        {"id": r["id"], "text": r["text"], "score": r["score"], "rank": i + 1}
        for i, r in enumerate(ranked)
    ]


def answer(graph, question: str, complete_text=None) -> dict:
    complete_text = complete_text or llm.complete_text
    found = snippets(graph, question)
    if not found:
        return {"answer": "No matching messages.", "snippets": [], "error": None}
    user = "Question: " + question + "\n\nSnippets:\n" + "\n".join(
        f"[{s['id']}] {s['text']}" for s in found
    )
    try:
        text = complete_text(PROMPT, user).strip()
        text = strip_citations(text, [s["id"] for s in found])
        return {"answer": text, "snippets": found, "error": None}
    except llm.LLMError as e:
        return {"answer": None, "snippets": found, "error": str(e)}
