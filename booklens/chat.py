"""The interactive chat REPL: one fixed-ceiling conversation over an assembled readable set.

Per `DECISIONS.md` section 7, `context.assemble` runs once at launch and the
resulting text is reused, byte-identical, as the stable, cacheable prefix of
every turn. There is no in-session way to move the ceiling; relaunching is.
"""

from __future__ import annotations

import contextlib
import itertools
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from booklens import db, progress
from booklens.chat_prompt import CONTEXT_PREFACE, SYSTEM_PROMPT
from booklens.context import AssembledContext
from booklens.llm.base import LLM, FatalLLMError, Message, Response, TransientLLMError, get_provider

DEFAULT_TEMPERATURE = 0.3
ANSWER_MAX_TOKENS = 2048

# api_messages[0] is the system prompt, api_messages[1] is the book-context
# message -- see booklens/llm/openrouter.py._build_messages. Both are fixed
# for the life of a session, so this index never changes turn to turn.
_STABLE_PREFIX_BREAKPOINT = 1

_CITATION_IN_TEXT_RE = re.compile(r"\[([^\[\]:\s]+:\d+:p\d+)\]")

_EXIT_COMMANDS = ("/exit", "/quit")

_HELP_TEXT = (
    "/exit           end the conversation\n"
    "/debug          toggle per-turn debug output\n"
    "/help           show this message\n"
    "Ctrl-C          cancel the current answer\n"
    "\n"
    "The reading position is fixed for this session -- relaunch with a "
    "different --chapter to change it."
)


def ephemeral_ceiling_conn(
    iconn: sqlite3.Connection, book_id: str, chapter_idx: int
) -> sqlite3.Connection:
    """A from-scratch, in-memory `book_progress` scoped to exactly `book_id`'s series.

    Earlier books (`book_order` lower than the target's) are `finished`, whole.
    The target book is `reading`, pinned at `chapter_idx`. Every later book, and
    every other series, gets no row at all. `data/progress.db` is never read or
    written -- see docs/implementation-notes.md for why.
    """
    clone = sqlite3.connect(":memory:")
    clone.row_factory = sqlite3.Row
    db.init_progress(clone)

    # set_position already cascades every earlier book in the series to
    # finished; reset_ceiling then pins the target exactly, never watermarked.
    progress.set_position(clone, iconn, book_id, status="reading", chapter_idx=chapter_idx)
    progress.reset_ceiling(clone, book_id, progress.chapter_end_seq(iconn, book_id, chapter_idx))
    return clone


def extract_citation_ids(text: str) -> list[str]:
    """Citation IDs referenced in an answer, in first-seen order, deduplicated."""
    seen: list[str] = []
    for match in _CITATION_IN_TEXT_RE.finditer(text):
        cid = match.group(1)
        if cid not in seen:
            seen.append(cid)
    return seen


def build_llm(provider_name: str = "openrouter") -> LLM:
    """The answering provider: Luna Pro (reasoning.mode=pro) by default, per DECISIONS.md section 13.

    Other provider names (e.g. 'fake' for tests) are constructed with no
    extra kwargs, since `reasoning_mode` is an OpenRouter-only parameter.
    """
    if provider_name == "openrouter":
        return get_provider("openrouter", reasoning_mode="pro")
    return get_provider(provider_name)


@dataclass(frozen=True)
class TurnResult:
    """What one call to `ChatSession.ask` produced, plus the accounting `--debug` needs."""

    text: str
    response: Response
    citation_ids: list[str]
    session_cost_usd: float


@dataclass
class ChatSession:
    """A conversation bounded to one `AssembledContext`, built once and reused every turn.

    `history` accumulates as plain (question, answer) message pairs, appended
    after the stable prefix -- never inserted into it -- so the prefix stays
    byte-identical across turns and the prompt cache stays warm.
    """

    llm: LLM
    assembled: AssembledContext
    temperature: float = DEFAULT_TEMPERATURE
    history: list[Message] = field(default_factory=list)
    session_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        # Built once at construction time so nothing about it can drift turn to turn.
        self._context_message = Message(role="user", content=CONTEXT_PREFACE + self.assembled.text)

    def stable_prefix_messages(self) -> list[Message]:
        """The messages that must never change turn to turn -- the cacheable prefix minus `system`."""
        return [self._context_message]

    def ask(self, question: str) -> TurnResult:
        """Send one turn: stable prefix, then accumulated history, then the new question."""
        messages = self.stable_prefix_messages() + self.history + [Message(role="user", content=question)]
        response = self.llm.complete(
            messages,
            system=SYSTEM_PROMPT,
            max_tokens=ANSWER_MAX_TOKENS,
            temperature=self.temperature,
            cache_breakpoint=_STABLE_PREFIX_BREAKPOINT,
        )
        self.history.append(Message(role="user", content=question))
        self.history.append(Message(role="assistant", content=response.text))
        self.session_cost_usd += response.cost_usd or 0.0
        return TurnResult(
            text=response.text,
            response=response,
            citation_ids=extract_citation_ids(response.text),
            session_cost_usd=self.session_cost_usd,
        )


def banner(title: str, chapter_label: str, assembled: AssembledContext, prior_titles: list[str] | None = None) -> str:
    """The one-line orientation printed at launch, naming every volume actually in context."""
    tokens_k = assembled.token_estimate // 1000
    prior = prior_titles or []
    head = ", ".join(prior) + " (whole) + " + title if prior else title
    # Some books label chapters "Chapter 5: ...", others just "5: ..." -- don't say "chapter" twice.
    where = chapter_label if chapter_label.lower().startswith("chapter") else f"chapter {chapter_label}"
    return f"{head} through {where} (~{tokens_k}k tokens in context)"


def format_debug(result: TurnResult, context_tokens: int) -> str:
    """Per-turn accounting: whether the cache breakpoint is actually working is the point of this."""
    r = result.response
    cost = f"{r.cost_usd:.4f}" if r.cost_usd is not None else "n/a"
    return (
        "  [debug] "
        f"context_tokens={context_tokens} prompt_tokens={r.input_tokens} "
        f"cached_tokens={r.cached_tokens} cache_write_tokens={r.cache_write_tokens} "
        f"turn_cost_usd={cost} session_cost_usd={result.session_cost_usd:.4f} "
        f"citations={result.citation_ids}"
    )


@contextlib.contextmanager
def _working_indicator(print_fn=print):
    """A spinner on stderr-equivalent stdout while a non-streamed call is in flight."""
    stop = threading.Event()

    def spin() -> None:
        for ch in itertools.cycle("|/-\\"):
            if stop.is_set():
                break
            print_fn(f"\r{ch} thinking...", end="", flush=True)
            time.sleep(0.1)
        print_fn("\r" + " " * 20 + "\r", end="", flush=True)

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


def run_repl(
    session: ChatSession,
    *,
    title: str,
    chapter_label: str,
    prior_titles: list[str] | None = None,
    debug: bool = False,
    input_fn=input,
    print_fn=print,
    indicator=_working_indicator,
) -> int:
    """Drive the read-eval-print loop until `/exit` or EOF.

    Ctrl-C at the prompt is a no-op (prints a hint); Ctrl-C during a turn
    cancels that turn without touching `session.history`.
    """
    print_fn(banner(title, chapter_label, session.assembled, prior_titles))
    print_fn("Type /help for commands.\n")

    while True:
        try:
            line = input_fn("> ")
        except EOFError:
            print_fn()
            return 0
        except KeyboardInterrupt:
            print_fn()
            print_fn("(use /exit or Ctrl-D to quit)")
            continue
        line = line.strip()
        if not line:
            continue
        if line in _EXIT_COMMANDS:
            return 0
        if line == "/help":
            print_fn(_HELP_TEXT)
            continue
        if line == "/debug":
            debug = not debug
            print_fn(f"debug: {'on' if debug else 'off'}")
            continue
        if line.startswith("/"):
            print_fn(f"unknown command: {line!r} (try /help)")
            continue

        try:
            with indicator(print_fn):
                result = session.ask(line)
        except KeyboardInterrupt:
            print_fn("(cancelled)")
            continue
        except (TransientLLMError, FatalLLMError) as exc:
            print_fn(f"error: {exc}")
            continue

        print_fn(result.text)
        if debug:
            print_fn(format_debug(result, session.assembled.token_estimate))
        print_fn()
