"""Tests for booklens.prompts: prompt assembly and strict response parsing.

All illustrative text below is invented -- no real book content, per project policy.
"""

from __future__ import annotations

import json

import pytest

from booklens import prompts
from booklens.llm.base import Message

VALID_DIGEST_MD = (
    "---\n"
    "book_id: invented\n"
    "chapter_idx: 0\n"
    "chapter_label: Ch 1\n"
    "part_label: Part One\n"
    "---\n"
    "## Events\n- invented event\n"
    "## State changes\n- invented change\n"
    "## Open questions\n- invented question\n"
)

VALID_ROLLUP_DIGEST_MD = (
    "---\n"
    "book_id: invented\n"
    "level: part\n"
    "target_label: Part One\n"
    "---\n"
    "## Events\n- invented event\n"
    "## State changes\n- invented change\n"
    "## Open questions\n- invented question\n"
)


def _valid_response(entities=None):
    return json.dumps({"digest_markdown": VALID_DIGEST_MD, "entities": entities or []})


# -- prompt assembly ----------------------------------------------------------


def test_build_chapter_prompt_hash_is_stable_across_calls():
    b1 = prompts.build_chapter_prompt(
        book_id="b1", chapter_idx=0, chapter_label="Ch 1", part_label=None,
        registry={"nodes": [], "edges": [], "attrs": []},
        paragraphs=[{"id": 1, "global_seq": 5, "text": "invented"}],
    )
    b2 = prompts.build_chapter_prompt(
        book_id="b2", chapter_idx=9, chapter_label="Ch 9", part_label="Part One",
        registry={"nodes": [{"id": 1}], "edges": [], "attrs": []},
        paragraphs=[{"id": 99, "global_seq": 500, "text": "different invented text"}],
    )
    assert b1.prompt_hash == b2.prompt_hash == prompts.CHAPTER_PROMPT_HASH


def test_chapter_prompt_hash_independent_of_book_text():
    """prompt_hash captures the template, not the content it was fed."""
    a = prompts.build_chapter_prompt(
        book_id="b", chapter_idx=0, chapter_label="Ch", part_label=None, registry={},
        paragraphs=[{"id": 1, "global_seq": 1, "text": "x"}],
    )
    b = prompts.build_chapter_prompt(
        book_id="b", chapter_idx=0, chapter_label="Ch", part_label=None, registry={},
        paragraphs=[{"id": 2, "global_seq": 2, "text": "y" * 5000}],
    )
    assert a.prompt_hash == b.prompt_hash


def test_chapter_prompt_carries_paragraph_text_in_user_message():
    bundle = prompts.build_chapter_prompt(
        book_id="b1", chapter_idx=0, chapter_label="Ch 1", part_label=None,
        registry={"nodes": [], "edges": [], "attrs": []},
        paragraphs=[{"id": 7, "global_seq": 5, "text": "INVENTED_MARKER_TEXT"}],
    )
    assert any("INVENTED_MARKER_TEXT" in m.content for m in bundle.messages)
    assert isinstance(bundle.messages[0], Message)


def test_build_rollup_prompt_never_needs_raw_paragraphs():
    bundle = prompts.build_rollup_prompt(
        book_id="b1", level="part", target_label="Part One", source_digests=[VALID_ROLLUP_DIGEST_MD]
    )
    assert bundle.prompt_hash == prompts.ROLLUP_PROMPT_HASH
    combined = bundle.system + "".join(m.content for m in bundle.messages)
    assert "para" not in combined.lower() or "source_digests" in combined  # sanity: no raw-para instruction leaked in
    parsed = json.loads(bundle.messages[0].content)
    assert parsed["source_digests"] == [VALID_ROLLUP_DIGEST_MD]


def test_chapter_and_rollup_prompt_hashes_differ():
    assert prompts.CHAPTER_PROMPT_HASH != prompts.ROLLUP_PROMPT_HASH


# -- chapter response parsing --------------------------------------------------


def test_parse_chapter_response_happy_path():
    entities = [
        {
            "designator": "Alpha",
            "node_kind": "named",
            "cite_para_id": 1,
            "attributes": [{"attr_kind": "trait", "value": "invented", "cite_para_id": 1}],
            "aliases": [],
        }
    ]
    result = prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1, 2})
    assert result.digest_markdown == VALID_DIGEST_MD
    assert len(result.entities) == 1
    assert result.entities[0].designator == "Alpha"
    assert result.entities[0].attributes[0].value == "invented"


def test_parse_chapter_response_unwraps_markdown_code_fence():
    """Some providers wrap JSON in ```json ... ``` -- strip it, don't reject it."""
    fenced = "```json\n" + _valid_response() + "\n```"
    result = prompts.parse_chapter_response(fenced, valid_para_ids={1, 2})
    assert result.digest_markdown == VALID_DIGEST_MD


def test_parse_rollup_response_unwraps_markdown_code_fence():
    fenced = "```json\n" + json.dumps({"digest_markdown": VALID_ROLLUP_DIGEST_MD}) + "\n```"
    assert prompts.parse_rollup_response(fenced) == VALID_ROLLUP_DIGEST_MD


def test_parse_chapter_response_rejects_non_json():
    with pytest.raises(ValueError):
        prompts.parse_chapter_response("not json at all", valid_para_ids={1})


def test_parse_chapter_response_rejects_non_object_json():
    with pytest.raises(ValueError):
        prompts.parse_chapter_response("[1, 2, 3]", valid_para_ids={1})


def test_parse_chapter_response_rejects_missing_digest_markdown():
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(json.dumps({"entities": []}), valid_para_ids={1})


def test_parse_chapter_response_rejects_digest_missing_section():
    bad_md = VALID_DIGEST_MD.replace("## Open questions", "## Something Else")
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(
            json.dumps({"digest_markdown": bad_md, "entities": []}), valid_para_ids={1}
        )


def test_parse_chapter_response_rejects_entity_missing_fields():
    entities = [{"designator": "Alpha"}]  # missing node_kind, cite_para_id
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1})


def test_parse_chapter_response_rejects_bad_node_kind():
    entities = [{"designator": "Alpha", "node_kind": "villain", "cite_para_id": 1}]
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1})


def test_parse_chapter_response_rejects_citation_outside_chapter():
    entities = [{"designator": "Alpha", "node_kind": "named", "cite_para_id": 999}]
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1, 2})


def test_parse_chapter_response_rejects_attribute_citation_outside_chapter():
    entities = [
        {
            "designator": "Alpha",
            "node_kind": "named",
            "cite_para_id": 1,
            "attributes": [{"attr_kind": "trait", "value": "x", "cite_para_id": 999}],
        }
    ]
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1})


def test_parse_chapter_response_rejects_alias_citation_outside_chapter():
    entities = [
        {
            "designator": "Alpha",
            "node_kind": "named",
            "cite_para_id": 1,
            "aliases": [{"other_designator": "Beta", "edge_type": "stated", "cite_para_id": 999}],
        }
    ]
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1})


def test_parse_chapter_response_rejects_bad_edge_type():
    entities = [
        {
            "designator": "Alpha",
            "node_kind": "named",
            "cite_para_id": 1,
            "aliases": [{"other_designator": "Beta", "edge_type": "definitely", "cite_para_id": 1}],
        }
    ]
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1})


def test_parse_chapter_response_all_or_nothing():
    """A malformed second entity must invalidate the whole response, not just itself."""
    entities = [
        {"designator": "Good", "node_kind": "named", "cite_para_id": 1},
        {"designator": "Bad", "node_kind": "not-a-kind", "cite_para_id": 1},
    ]
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(_valid_response(entities), valid_para_ids={1})


# -- rollup response parsing ----------------------------------------------------


def test_parse_rollup_response_happy_path():
    text = prompts.parse_rollup_response(json.dumps({"digest_markdown": VALID_ROLLUP_DIGEST_MD}))
    assert text == VALID_ROLLUP_DIGEST_MD


def test_parse_rollup_response_rejects_non_json():
    with pytest.raises(ValueError):
        prompts.parse_rollup_response("garbage")


def test_parse_rollup_response_rejects_missing_field():
    with pytest.raises(ValueError):
        prompts.parse_rollup_response(json.dumps({}))


def test_parse_rollup_response_rejects_missing_section():
    bad_md = VALID_ROLLUP_DIGEST_MD.replace("## Events", "## Stuff")
    with pytest.raises(ValueError):
        prompts.parse_rollup_response(json.dumps({"digest_markdown": bad_md}))


# -- front matter validation ----------------------------------------------------


def test_parse_chapter_response_rejects_missing_front_matter():
    bad_md = (
        "## Events\n- invented event\n"
        "## State changes\n- invented change\n"
        "## Open questions\n- invented question\n"
    )
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(
            json.dumps({"digest_markdown": bad_md, "entities": []}), valid_para_ids={1}
        )


def test_parse_chapter_response_rejects_front_matter_missing_key():
    bad_md = VALID_DIGEST_MD.replace("part_label: Part One\n", "")
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(
            json.dumps({"digest_markdown": bad_md, "entities": []}), valid_para_ids={1}
        )


def test_parse_chapter_response_rejects_front_matter_extra_key():
    bad_md = VALID_DIGEST_MD.replace(
        "part_label: Part One\n", "part_label: Part One\npov: Alpha (implied narrator)\n"
    )
    with pytest.raises(ValueError):
        prompts.parse_chapter_response(
            json.dumps({"digest_markdown": bad_md, "entities": []}), valid_para_ids={1}
        )


def test_parse_rollup_response_rejects_missing_front_matter():
    bad_md = (
        "## Events\n- invented event\n"
        "## State changes\n- invented change\n"
        "## Open questions\n- invented question\n"
    )
    with pytest.raises(ValueError):
        prompts.parse_rollup_response(json.dumps({"digest_markdown": bad_md}))


def test_parse_rollup_response_rejects_front_matter_missing_key():
    bad_md = VALID_ROLLUP_DIGEST_MD.replace("target_label: Part One\n", "")
    with pytest.raises(ValueError):
        prompts.parse_rollup_response(json.dumps({"digest_markdown": bad_md}))


def test_parse_rollup_response_rejects_front_matter_extra_key():
    bad_md = VALID_ROLLUP_DIGEST_MD.replace(
        "target_label: Part One\n", "target_label: Part One\nchapter_idx: 3\n"
    )
    with pytest.raises(ValueError):
        prompts.parse_rollup_response(json.dumps({"digest_markdown": bad_md}))


# -- strict=False literal-newline handling ---------------------------------------


def test_parse_chapter_response_accepts_literal_newlines_in_digest_markdown():
    """The model must escape newlines in digest_markdown as \\n but doesn't always;
    strict=False accepts the literal control characters without weakening any other check."""
    raw = (
        '{"digest_markdown": "---\n'
        "book_id: invented\n"
        "chapter_idx: 0\n"
        "chapter_label: Ch 1\n"
        "part_label: Part One\n"
        "---\n"
        "## Events\n- invented event\n"
        "## State changes\n- invented change\n"
        "## Open questions\n- invented question\n"
        '", "entities": []}'
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)  # sanity: this really does fail under strict=True

    result = prompts.parse_chapter_response(raw, valid_para_ids={1})
    assert "## Events" in result.digest_markdown
    assert result.entities == []


def test_parse_rollup_response_accepts_literal_newlines_in_digest_markdown():
    raw = (
        '{"digest_markdown": "---\n'
        "book_id: invented\n"
        "level: part\n"
        "target_label: Part One\n"
        "---\n"
        "## Events\n- invented event\n"
        "## State changes\n- invented change\n"
        "## Open questions\n- invented question\n"
        '"}'
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)  # sanity: this really does fail under strict=True

    text = prompts.parse_rollup_response(raw)
    assert "## Events" in text
