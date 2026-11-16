"""
Ask the manual: examiners ask a question and get an answer from the MoCA manuals (a small RAG).

How it works, in three steps:
  1. Read   -- every PDF in knowledge/manuals/ is split into short passages (once, on first use).
  2. Find   -- the passages that share the most words with the question are picked (BM25 search).
  3. Answer -- Claude writes the answer using only those passages, and says which ones it used.

To change what it knows, add or remove PDFs in knowledge/manuals/ and restart the server.
Needs ANTHROPIC_API_KEY in .env.
"""

import logging
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from moca_common import PROJECT_DIR

from .auth import current_examiner
from .db import Examiner

log = logging.getLogger("moca")
router = APIRouter(prefix="/api/manual")

MANUALS_DIR = PROJECT_DIR / "knowledge" / "manuals"
MODEL = os.environ.get("MOCA_MANUAL_MODEL", "claude-opus-5-5")
TOP_K = 6                 # passages given to Claude per question
CHUNK_CHARS = 1200        # about a long paragraph
OVERLAP_CHARS = 200       # so a rule cut in half still appears whole in one passage

SYSTEM_PROMPT = """You help examiners give and score the Montreal Cognitive Assessment (MoCA).
You are given numbered passages from the official MoCA instruction manuals. Answer the examiner's
question using only those passages.

- Cite the passages you rely on with their numbers in square brackets, like [2].
- If the passages don't contain the answer, say so plainly and don't fill the gap from memory.
- Manual versions differ (for example 7.x and 8.x). When the version matters, say which one each rule comes from.
- Be short and practical: the examiner may be in the middle of a test. Use a short list for steps or scoring rules.
- You explain how to give and score the test. You don't diagnose a patient."""

STOPWORDS = set("""a an and are as at be but by can do does for from has have how i if in into is it its
of on or so that the their them then there these they this to was what when where which who why will
with you your should would""".split())


@dataclass
class Passage:
    source: str
    page: int
    text: str
    words: Counter
    length: int


def _stem(word):
    """Rough word root, so "drawing", "draws" and "drawn" all match "draw"."""
    for end in ("ing", "ed", "es", "s", "n"):
        if word.endswith(end) and len(word) - len(end) >= 4:
            return word[: -len(end)]
    return word


def _words(text):
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def _title(filename):
    return re.sub(r"[_]+", " ", filename.rsplit(".", 1)[0]).strip()


def _split(text):
    """Pieces of about CHUNK_CHARS, cut at a line break where possible."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    pieces, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            end = cut if cut > 0 else end
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP_CHARS, start + 1)
    return [p for p in pieces if len(p) > 40]


class Library:
    """Every passage of every manual, with what BM25 search needs."""

    def __init__(self, folder):
        from pypdf import PdfReader

        self.passages = []
        for pdf in sorted(folder.glob("*.pdf")):
            try:
                pages = PdfReader(pdf).pages
            except Exception as e:                    # one bad file shouldn't stop the rest
                log.error("could not read %s: %s", pdf.name, e)
                continue
            for number, page in enumerate(pages, start=1):
                for piece in _split(page.extract_text() or ""):
                    words = _words(piece)
                    self.passages.append(Passage(_title(pdf.name), number, piece, Counter(words), len(words)))
        n = len(self.passages) or 1
        self.avg_len = sum(p.length for p in self.passages) / n
        seen_in = Counter(w for p in self.passages for w in p.words)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in seen_in.items()}
        log.info("manual search ready: %d passages from %s", len(self.passages), folder)

    def search(self, question, k=TOP_K, k1=1.5, b=0.75):
        terms = set(_words(question))
        scored = []
        for p in self.passages:
            score = 0.0
            for t in terms:
                f = p.words.get(t, 0)
                if f:
                    score += self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * p.length / self.avg_len))
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:k]]


_library = None
_library_lock = threading.Lock()


def library():
    global _library
    with _library_lock:
        if _library is None:
            _library = Library(MANUALS_DIR)
        return _library


_client = None


def claude():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def answer(question, passages):
    """Claude's answer to the question, using only the numbered passages."""
    excerpts = "\n\n".join(f'<passage n="{i}" source="{p.source}" page="{p.page}">\n{p.text}\n</passage>'
                           for i, p in enumerate(passages, start=1))
    response = claude().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},        # a short lookup, not a hard problem
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                     # if a safety check declines, another model answers
        messages=[{"role": "user", "content": f"<passages>\n{excerpts}\n</passages>\n\nQuestion: {question}"}],
    )
    if response.stop_reason == "refusal":
        return "Sorry, I can't answer that one. Try asking about how to give or score a task."
    return "".join(b.text for b in response.content if b.type == "text").strip()


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post("/ask")
def ask(body: Question, _: Examiner = Depends(current_examiner)):
    question = body.question.strip()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "Ask the manual isn't set up yet: add ANTHROPIC_API_KEY to .env")
    lib = library()
    if not lib.passages:
        raise HTTPException(503, "no manuals found: put the PDF manuals in knowledge/manuals/")
    passages = lib.search(question)
    if not passages:
        return {"answer": "I couldn't find anything about that in the manuals. Try other words, "
                          "for example the task's name (\"clock drawing\", \"delayed recall\").", "sources": []}
    try:
        text = answer(question, passages)
    except anthropic.AuthenticationError as e:
        raise HTTPException(503, "the ANTHROPIC_API_KEY in .env isn't valid") from e
    except anthropic.RateLimitError as e:
        raise HTTPException(429, "too many questions at once, please wait a moment and try again") from e
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        log.error("manual answer failed: %s", e)
        raise HTTPException(502, "couldn't reach the answering service, please try again") from e
    return {"answer": text,
            "sources": [{"n": i, "source": p.source, "page": p.page, "text": p.text}
                        for i, p in enumerate(passages, start=1)]}
