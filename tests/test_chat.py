"""Tests for booklens.chat: the REPL, its cache-breakpoint contract, the
ephemeral (never-persisted) ceiling, and the CLI wiring around it.

Most tests use a hand-rolled mock LLM for full call introspection rather
than `booklens.llm.fake.FakeLLM`, though `FakeLLM.complete` does accept
`cache_breakpoint` (it records and ignores it). No test here makes a live
API call.
"""

from __future__ import annotations

import json

import pytest

from booklens import chat, cli, db
from booklens.context import AssembledContext
from booklens.llm.base import Message, Response
from tests.test_ingest import _make_epub, _simple_epub


# -- a minimal mock LLM implementing the real cache_breakpoint contract -----


class MockLLM:
    """Records every call it receives and returns scripted text, deterministically."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["a scripted answer"]
        self.calls: list[dict] = []

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        cache_breakpoint: int | None = None,
    ) -> Response:
        self.calls.append(
            {
                "messages": list(messages),
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "cache_breakpoint": cache_breakpoint,
            }
        )
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        text = self.responses[index]
        return Response(
            text=text,
            stop_reason="end_turn",
            input_tokens=1000 * len(self.calls),
            output_tokens=50,
            model="mock-model",
            cost_usd=0.01,
            cached_tokens=900 if len(self.calls) > 1 else 0,
            cache_write_tokens=100 if len(self.calls) == 1 else 0,
        )


def _fixture_context(text="[rr:0:p0] a paragraph of invented text.") -> AssembledContext:
    return AssembledContext(
        text=text,
        para_count=1,
        max_global_seq=db.global_seq(1, 0, 0),
        token_estimate=len(text) // 4,
        chapter_span=("rr: Prologue", "rr: Prologue"),
        content_hash="deadbeef",
    )


# -- ChatSession: the cache-breakpoint contract ------------------------------


def test_ask_sends_system_and_marks_stable_prefix_breakpoint():
    llm = MockLLM()
    session = chat.ChatSession(llm, _fixture_context())
    session.ask("who is in the prologue?")

    call = llm.calls[0]
    assert call["system"] == chat.SYSTEM_PROMPT
    assert call["cache_breakpoint"] == 1
    # message index 0 is the book-context message; the breakpoint (index 1 in
    # the *API* array) accounts for `system` occupying index 0 there.
    assert call["messages"][0].content.startswith(session.stable_prefix_messages()[0].content[:20])


def test_stable_prefix_is_byte_identical_across_turns():
    llm = MockLLM(responses=["first answer", "second answer"])
    session = chat.ChatSession(llm, _fixture_context())

    session.ask("question one")
    session.ask("question two")

    first_call, second_call = llm.calls
    assert first_call["system"] == second_call["system"]
    # The book-context message (messages[0]) must be byte-identical, and it
    # must still be messages[0] on turn two despite history accumulating.
    assert first_call["messages"][0].content == second_call["messages"][0].content
    assert first_call["messages"][0] == second_call["messages"][0]


def test_conversation_history_accumulates_after_the_stable_prefix():
    llm = MockLLM(responses=["first answer", "second answer"])
    session = chat.ChatSession(llm, _fixture_context())

    session.ask("question one")
    session.ask("question two")
    second_call_messages = llm.calls[1]["messages"]

    # [context, q1, a1, q2]
    assert len(second_call_messages) == 4
    assert second_call_messages[1] == Message(role="user", content="question one")
    assert second_call_messages[2] == Message(role="assistant", content="first answer")
    assert second_call_messages[3] == Message(role="user", content="question two")


def test_context_assembled_only_once_and_reused_every_turn():
    llm = MockLLM(responses=["a1", "a2", "a3"])
    assembled = _fixture_context()
    session = chat.ChatSession(llm, assembled)

    session.ask("one")
    session.ask("two")
    session.ask("three")

    # The same AssembledContext object backs every turn's context message --
    # nothing re-derives or re-assembles it per turn.
    assert session.assembled is assembled
    contents = {c["messages"][0].content for c in llm.calls}
    assert len(contents) == 1


def test_session_cost_accumulates_across_turns():
    llm = MockLLM(responses=["a1", "a2"])
    session = chat.ChatSession(llm, _fixture_context())

    r1 = session.ask("one")
    r2 = session.ask("two")

    assert r1.session_cost_usd == pytest.approx(0.01)
    assert r2.session_cost_usd == pytest.approx(0.02)


def test_citation_ids_extracted_from_answer_text():
    llm = MockLLM(responses=["Darrow says this [rr:5:p12] and also this [rr:5:p12] and [rr:6:p01]."])
    session = chat.ChatSession(llm, _fixture_context())
    result = session.ask("what happens?")
    assert result.citation_ids == ["rr:5:p12", "rr:6:p01"]


def test_citation_ids_empty_when_answer_has_none():
    llm = MockLLM(responses=["nothing in what you've read covers this."])
    session = chat.ChatSession(llm, _fixture_context())
    result = session.ask("does it end well?")
    assert result.citation_ids == []


# -- run_repl: commands ------------------------------------------------------


def _scripted_input(lines):
    it = iter(lines)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return _input


def _no_wait_indicator(print_fn=print):
    import contextlib

    @contextlib.contextmanager
    def _cm():
        yield

    return _cm()


def _recording_print(sink: list):
    """A `print`-compatible sink (accepts `end`/`flush`/no-args) that appends whole lines."""

    def _print(*args, **kwargs):
        sink.append(" ".join(str(a) for a in args))

    return _print


def test_repl_exit_command_returns_cleanly():
    llm = MockLLM()
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    rc = chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert rc == 0
    assert not llm.calls
    assert any("Sample Book" in line for line in printed)


def test_repl_debug_toggle_shows_debug_block_only_when_on():
    llm = MockLLM(responses=["an answer [rr:1:p01]."])
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["/debug", "what happens?", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert any("debug: on" in line for line in printed)
    assert any("[debug]" in line for line in printed)
    assert any("cached_tokens=" in line for line in printed)


def test_repl_debug_off_by_default_no_debug_block():
    llm = MockLLM(responses=["an answer."])
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["what happens?", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert not any("[debug]" in line for line in printed)


def test_repl_help_command():
    llm = MockLLM()
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["/help", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert any("/exit" in line for line in printed)
    assert not llm.calls


def test_repl_eof_exits_cleanly():
    llm = MockLLM()
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    rc = chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input([]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert rc == 0


def test_repl_unknown_command_reports_and_continues():
    llm = MockLLM()
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["/nonsense", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert any("unknown command" in line for line in printed)
    assert not llm.calls


def test_repl_multiturn_asks_twice_and_accumulates_history():
    llm = MockLLM(responses=["answer one", "answer two"])
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["question one", "question two", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert len(llm.calls) == 2
    assert len(llm.calls[1]["messages"]) == 4  # context + q1 + a1 + q2


# -- run_repl: cancellation and transient failures ---------------------------


class _RaisingLLM:
    """An LLM whose `complete` always raises the given exception."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls = []

    def complete(self, messages, *, system=None, max_tokens=4096, temperature=0.0, cache_breakpoint=None):
        self.calls.append(messages)
        raise self._exc


def test_repl_ctrl_c_during_turn_cancels_without_touching_history():
    llm = _RaisingLLM(KeyboardInterrupt())
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    rc = chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["what happens?", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert rc == 0
    assert session.history == []
    assert any("cancelled" in line for line in printed)
    assert len(llm.calls) == 1


def test_repl_ctrl_c_at_prompt_does_not_exit(monkeypatch):
    llm = MockLLM()
    session = chat.ChatSession(llm, _fixture_context())
    printed = []

    lines = iter(["/exit"])

    def _input(prompt=""):
        if not printed_ctrl_c["done"]:
            printed_ctrl_c["done"] = True
            raise KeyboardInterrupt
        try:
            return next(lines)
        except StopIteration:
            raise EOFError

    printed_ctrl_c = {"done": False}

    rc = chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_input,
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert rc == 0
    assert any("use /exit or Ctrl-D to quit" in line for line in printed)
    assert not llm.calls


def test_repl_transient_error_during_turn_prints_error_and_keeps_history_empty():
    from booklens.llm.base import TransientLLMError

    llm = _RaisingLLM(TransientLLMError("rate limited"))
    session = chat.ChatSession(llm, _fixture_context())
    printed = []
    rc = chat.run_repl(
        session,
        title="Sample Book",
        chapter_label="1: The Start",
        input_fn=_scripted_input(["what happens?", "/exit"]),
        print_fn=_recording_print(printed),
        indicator=_no_wait_indicator,
    )
    assert rc == 0
    assert session.history == []
    assert any("error:" in line and "rate limited" in line for line in printed)


# -- build_llm: provider selection -------------------------------------------


def test_build_llm_openrouter_gets_pro_reasoning_mode(monkeypatch):
    from booklens.llm.openrouter import OpenRouterProvider

    llm = chat.build_llm("openrouter")
    assert isinstance(llm, OpenRouterProvider)
    assert llm.reasoning_mode == "pro"


def test_build_llm_fake_does_not_pass_reasoning_mode():
    from booklens.llm.fake import FakeLLM

    llm = chat.build_llm("fake")
    assert isinstance(llm, FakeLLM)


def test_fake_llm_accepts_cache_breakpoint():
    """Regression for coordinator fix 3: `--provider fake` broke on the first real question
    because `FakeLLM.complete` rejected `cache_breakpoint`, which `ChatSession.ask` always sends."""
    from booklens.llm.fake import FakeLLM

    llm = FakeLLM(responses=["an answer"])
    session = chat.ChatSession(llm, _fixture_context())
    result = session.ask("does the fake provider work end to end?")
    assert result.text == "an answer"
    assert llm.calls[0].cache_breakpoint == 1


# -- CLI wiring: resolve_chapter_ref failure and clean startup/exit ---------


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_cli_chat_fake_provider_answers_a_question(data_dir, capsys, monkeypatch):
    """End-to-end regression for fix 3: asking a real question through `--provider fake` must not crash."""
    import io

    epub = _simple_epub(data_dir, name="book.epub")
    rc = cli.main(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO("what happens in chapter 1?\n/exit\n"))
    rc = cli.main(["chat", "--book", "sample-book", "--chapter", "1", "--provider", "fake"])
    assert rc == 0


def test_cli_chat_unresolvable_chapter_exits_with_clear_error(data_dir, capsys, monkeypatch):
    epub = _simple_epub(data_dir, name="book.epub")
    rc = cli.main(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    capsys.readouterr()

    rc = cli.main(["chat", "--book", "sample-book", "--chapter", "999", "--provider", "fake"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown chapter reference" in err
    assert "valid printed chapters" in err


def test_cli_chat_banner_and_immediate_exit(data_dir, capsys, monkeypatch):
    import io

    epub = _simple_epub(data_dir, name="book.epub")
    rc = cli.main(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO("/exit\n"))
    rc = cli.main(["chat", "--book", "sample-book", "--chapter", "1", "--provider", "fake"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Sample Book" in out
    assert "tokens in context" in out


def test_cli_chat_does_not_change_real_progress_status(data_dir, capsys, monkeypatch):
    """`--chapter` is a lens on the corpus, not a claim the reader read anything -- see coordinator fix 1."""
    import io

    epub = _simple_epub(data_dir, name="book.epub")
    cli.main(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO("/exit\n"))
    cli.main(["chat", "--book", "sample-book", "--chapter", "1", "--provider", "fake"])
    capsys.readouterr()

    rc = cli.main(["books", "--json"])
    books = json.loads(capsys.readouterr().out)
    sample = next(b for b in books if b["id"] == "sample-book")
    assert sample["status"] == "unread"


def test_cli_chat_leaves_progress_db_byte_identical(data_dir, capsys, monkeypatch):
    """A chat run -- even the immediate-`/exit` path -- must never write to `data/progress.db`."""
    import io
    from pathlib import Path

    epub = _simple_epub(data_dir, name="book.epub")
    cli.main(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    progress_db = Path(str(data_dir)) / "data" / "progress.db"
    assert progress_db.is_file()
    before = progress_db.read_bytes()

    monkeypatch.setattr("sys.stdin", io.StringIO("/exit\n"))
    rc = cli.main(["chat", "--book", "sample-book", "--chapter", "1", "--provider", "fake"])
    assert rc == 0
    capsys.readouterr()

    after = progress_db.read_bytes()
    assert before == after


def _multi_chapter_epub(tmp_path, name="long_book.epub", title="Long Book", n_chapters=6):
    """A synthetic book with `n_chapters` numbered chapters, each one paragraph,
    invented text only -- enough chapters to exercise a descending `--chapter` sequence."""
    docs = [(f"Chapter {i}", [f"Paragraph text for invented chapter {i}."]) for i in range(1, n_chapters + 1)]
    return _make_epub(tmp_path / name, title, docs)


def _chat_banner(data_dir, monkeypatch, capsys, book_id: str, chapter: str) -> str:
    """Run one chat session to an immediate `/exit`, returning the printed banner line."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("/exit\n"))
    rc = cli.main(["chat", "--book", book_id, "--chapter", chapter, "--provider", "fake"])
    assert rc == 0
    out = capsys.readouterr().out
    return out.splitlines()[0]


def test_ceiling_is_exact_and_ephemeral_across_descending_chat_runs(data_dir, capsys, monkeypatch):
    """A later, *earlier* --chapter must not be poisoned by an earlier, later one.

    Regression for coordinator fix 1: `progress.set_position`'s watermark only
    ever rises, so persisting it made every `--chapter` after the first a
    silent no-op once a higher one had been used.
    """
    epub = _multi_chapter_epub(data_dir)
    rc = cli.main(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    capsys.readouterr()

    banner_high = _chat_banner(data_dir, monkeypatch, capsys, "long-book", "5")
    assert "Chapter 5" in banner_high
    assert "Chapter 6" not in banner_high

    banner_low = _chat_banner(data_dir, monkeypatch, capsys, "long-book", "2")
    assert "Chapter 2" in banner_low
    assert "Chapter 3" not in banner_low
    assert "Chapter 5" not in banner_low


def test_chat_pulls_in_earlier_series_books_whole_even_if_never_marked_read(data_dir, capsys, monkeypatch):
    """Nobody reads book 2 without book 1 -- the session must include book 1 whole,
    even though `data/progress.db` has never been told the reader touched it (problem a)."""
    import io

    epub_a = _multi_chapter_epub(data_dir, name="a.epub", title="Book A", n_chapters=4)
    epub_b = _multi_chapter_epub(data_dir, name="b.epub", title="Book B", n_chapters=4)
    cli.main(["ingest", str(epub_a), "--series", "s1", "--start-order", "1"])
    cli.main(["ingest", str(epub_b), "--series", "s1", "--start-order", "2"])
    capsys.readouterr()

    # Book A has no real progress at all -- still unread.
    monkeypatch.setattr("sys.stdin", io.StringIO("what happens in book a?\n/exit\n"))
    rc = cli.main(["chat", "--book", "book-b", "--chapter", "1", "--provider", "fake"])
    assert rc == 0
    out = capsys.readouterr().out
    banner_line = out.splitlines()[0]
    assert "Book A" in banner_line
    assert "(whole)" in banner_line

    # Book A's real progress must remain untouched -- still unread.
    rc = cli.main(["books", "--json"])
    books = json.loads(capsys.readouterr().out)
    book_a = next(b for b in books if b["id"] == "book-a")
    assert book_a["status"] == "unread"


def test_chat_ignores_real_progress_from_a_later_book_in_the_series(data_dir, capsys, monkeypatch):
    """A session pinned at book 1 must not silently drag in book 3's content just
    because the reader has genuinely finished book 3 in real life (problem b)."""
    import io

    epub_a = _multi_chapter_epub(data_dir, name="a.epub", title="Book A", n_chapters=4)
    epub_b = _multi_chapter_epub(data_dir, name="b.epub", title="Book B", n_chapters=4)
    cli.main(["ingest", str(epub_a), "--series", "s1", "--start-order", "1"])
    cli.main(["ingest", str(epub_b), "--series", "s1", "--start-order", "2"])
    capsys.readouterr()

    # Book B (later in the series) has real, persisted progress: finished.
    rc = cli.main(["progress", "book-b", "--status", "finished"])
    assert rc == 0
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", io.StringIO("/exit\n"))
    rc = cli.main(["chat", "--book", "book-a", "--chapter", "1", "--provider", "fake"])
    assert rc == 0
    out = capsys.readouterr().out
    banner_line = out.splitlines()[0]
    # Only book A (and nothing later) may be named as in context.
    assert "Book B" not in banner_line

    # Book B's real progress must be untouched by the session.
    rc = cli.main(["books", "--json"])
    books = json.loads(capsys.readouterr().out)
    book_b = next(b for b in books if b["id"] == "book-b")
    assert book_b["status"] == "finished"
