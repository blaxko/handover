"""Keyword RAG baseline (F7): top 3 Messages from the FalkorDB full-text index, then the LLM.

The baseline sees the same messages as the graph, and answers only from its top 3 snippets.
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


def search_terms(question: str) -> str:
    """Keyword query: words of the question, minus a few stopwords, OR-joined."""
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", question)]
    terms = [w for w in words if w not in STOPWORDS]
    return " | ".join(terms)


def snippets(graph, question: str) -> list[dict]:
    q = search_terms(question)
    if not q:
        return []
    rows = db.read(graph, queries.B1_KEYWORD_SEARCH, {"q": q})[:TOP_K]
    return [
        {"id": r["id"], "text": r["text"], "score": r["score"], "rank": i + 1}
        for i, r in enumerate(rows)
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
