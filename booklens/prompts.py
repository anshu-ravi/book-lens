"""Prompt templates for the digest pass, and strict parsing of their JSON responses.

Templates are invented instructions only -- no real book text ever appears here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from booklens.llm.base import Message

_VALID_NODE_KINDS = {"named", "unnamed"}
_VALID_EDGE_TYPES = {"stated", "inferable"}

_DIGEST_SECTION_HEADERS = ("## Events", "## State changes", "## Open questions")

_CHAPTER_FRONT_MATTER_KEYS = ("book_id", "chapter_idx", "chapter_label", "part_label")
_ROLLUP_FRONT_MATTER_KEYS = ("book_id", "level", "target_label")

_CHAPTER_SYSTEM_TEMPLATE = """\
You are building a spoiler-safe digest of one chapter for a reading companion app.

You will be given:
- the entity registry as known BEFORE this chapter (designators, aliases, attributes)
- the raw paragraphs of exactly one chapter

You have not seen, and must not assume anything about, any chapter after this one.

The digest is a ROUTING INDEX, not a summary for reading. It exists so a later
agent can decide which raw paragraphs are worth fetching -- it is never read on
its own, and detail always belongs in the raw text, one hop away via
source_paras. Treat the raw chapter as the thing being compressed, not
paraphrased: the digest must be dramatically shorter than the chapter, not
merely reworded.

Hard limits on digest_markdown, regardless of chapter length:
- At most 5 bullets under "## Events", at most 3 under "## State changes",
  at most 2 under "## Open questions".
- Each bullet is ONE short clause (a few words), never a full sentence with
  subordinate clauses -- write "duel, X wins" not "X and Y fought a duel in
  which X ultimately prevailed after a tense exchange."
- The entire digest body (everything after the front matter) must stay under
  roughly 250 words, no matter how long or eventful the chapter was.

The digest_markdown front matter is exactly these four fields, in this order,
delimited by "---" lines, copied from the values given to you in the user
payload -- do not decide their values and do not invent any other field:

---
book_id: <the book_id given to you>
chapter_idx: <the chapter_idx given to you>
chapter_label: <the chapter_label given to you>
part_label: <the part_label given to you>
---

Respond with a single JSON object, no other text, shaped exactly like this:

{
  "digest_markdown": "<the front matter above, followed by "
                      "'## Events', '## State changes', and '## Open questions' sections>",
  "entities": [
    {
      "designator": "<string, the surface form used for this entity>",
      "node_kind": "named" | "unnamed",
      "cite_para_id": <int, a paragraph id from THIS chapter that grounds this designator>,
      "attributes": [
        {"attr_kind": "<string>", "value": "<string>", "cite_para_id": <int, in this chapter>}
      ],
      "aliases": [
        {
          "other_designator": "<string, a designator this one corefers with>",
          "edge_type": "stated" | "inferable",
          "cite_para_id": <int, in this chapter>
        }
      ]
    }
  ]
}

Only cite paragraph ids that appear in this chapter's input. Only report entities,
attributes, and aliases that are stated or clearly inferable from this chapter's
text or the prior registry -- never from anything you might otherwise know.
"""

_ROLLUP_SYSTEM_TEMPLATE = """\
You are rolling up several digests into one coarser digest for a reading companion app.

You will be given the finer-grained digests that make up the target range, and
nothing else -- no raw book text. Do not invent content beyond what the source
digests state.

The result is a ROUTING INDEX, not a summary for reading, and it must compress
its sources, not concatenate them. Hard limits on digest_markdown regardless
of how many source digests you were given: at most 5 bullets under
"## Events", at most 3 under "## State changes", at most 2 under
"## Open questions", each a short clause rather than a full sentence, and the
entire digest body under roughly 250 words.

The digest_markdown front matter is exactly these three fields, in this order,
delimited by "---" lines, copied from the values given to you in the user
payload -- do not decide their values and do not invent any other field. Note
there is no single chapter_idx at this level; do not include one.

---
book_id: <the book_id given to you>
level: <the level given to you>
target_label: <the target_label given to you>
---

Respond with a single JSON object, no other text, shaped exactly like this:

{
  "digest_markdown": "<the front matter above, followed by "
                      "'## Events', '## State changes', and '## Open questions' sections>"
}
"""

CHAPTER_PROMPT_HASH = hashlib.sha256(_CHAPTER_SYSTEM_TEMPLATE.encode("utf-8")).hexdigest()[:16]
ROLLUP_PROMPT_HASH = hashlib.sha256(_ROLLUP_SYSTEM_TEMPLATE.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PromptBundle:
    """A ready-to-send prompt plus the hash identifying the template version that built it."""

    system: str
    messages: list[Message]
    prompt_hash: str


def build_chapter_prompt(
    *,
    book_id: str,
    chapter_idx: int,
    chapter_label: str,
    part_label: str | None,
    registry: dict,
    paragraphs: list[dict],
) -> PromptBundle:
    """Assemble the one call that produces a chapter's digest and its new entities.

    `registry` and `paragraphs` must already come from a `CausalWindow` bounded
    at this chapter's own `end_seq` -- this function trusts its caller for the
    causal bound and only shapes what gets sent.
    """
    payload = {
        "book_id": book_id,
        "chapter_idx": chapter_idx,
        "chapter_label": chapter_label,
        "part_label": part_label,
        "registry": registry,
        "paragraphs": [
            {
                "para_id": p["id"],
                "global_seq": p["global_seq"],
                "text": p["text"],
            }
            for p in paragraphs
        ],
    }
    user_content = json.dumps(payload, indent=2, default=str)
    return PromptBundle(
        system=_CHAPTER_SYSTEM_TEMPLATE,
        messages=[Message(role="user", content=user_content)],
        prompt_hash=CHAPTER_PROMPT_HASH,
    )


def build_rollup_prompt(
    *,
    book_id: str,
    level: str,
    target_label: str,
    source_digests: list[str],
) -> PromptBundle:
    """Assemble a rollup call from finer digests only -- never raw paragraph text."""
    payload = {
        "book_id": book_id,
        "level": level,
        "target_label": target_label,
        "source_digests": source_digests,
    }
    user_content = json.dumps(payload, indent=2, default=str)
    return PromptBundle(
        system=_ROLLUP_SYSTEM_TEMPLATE,
        messages=[Message(role="user", content=user_content)],
        prompt_hash=ROLLUP_PROMPT_HASH,
    )


@dataclass(frozen=True)
class EntityAttributeRecord:
    """One attribute assertion the model made about one entity in this chapter."""

    attr_kind: str
    value: str
    cite_para_id: int


@dataclass(frozen=True)
class EntityAliasRecord:
    """One coreference assertion the model made between two designators."""

    other_designator: str
    edge_type: str
    cite_para_id: int


@dataclass(frozen=True)
class EntityRecord:
    """One entity the model reported for this chapter, with its grounding citation."""

    designator: str
    node_kind: str
    cite_para_id: int
    attributes: list[EntityAttributeRecord]
    aliases: list[EntityAliasRecord]


@dataclass(frozen=True)
class ChapterExtraction:
    """The fully parsed, validated result of one chapter prompt call."""

    digest_markdown: str
    entities: list[EntityRecord]


def _require_str(d: dict, key: str, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{where}: field {key!r} must be a non-empty string, got {v!r}")
    return v


def _require_int(d: dict, key: str, where: str) -> int:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{where}: field {key!r} must be an int, got {v!r}")
    return v


def _require_cite(cite_para_id: int, valid_para_ids: set[int], where: str) -> None:
    if cite_para_id not in valid_para_ids:
        raise ValueError(
            f"{where}: cite_para_id {cite_para_id} does not belong to this chapter "
            f"-- rejecting to avoid trusting an invented or misattributed citation"
        )


def _validate_digest_markdown(markdown: str, where: str, front_matter_keys: tuple[str, ...]) -> None:
    """Check the required '## ...' sections and the exact front-matter key set for this digest kind."""
    for header in _DIGEST_SECTION_HEADERS:
        if header not in markdown:
            raise ValueError(f"{where}: digest_markdown is missing required section {header!r}")

    parts = markdown.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{where}: digest_markdown is missing '---'-delimited front matter")
    front_matter = parts[1]

    found_keys = []
    for line in front_matter.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        key = line.split(":", 1)[0].strip()
        found_keys.append(key)

    missing = [k for k in front_matter_keys if k not in found_keys]
    extra = [k for k in found_keys if k not in front_matter_keys]
    if missing or extra:
        raise ValueError(
            f"{where}: front matter keys must be exactly {list(front_matter_keys)}, "
            f"got {found_keys!r} (missing {missing!r}, extra {extra!r})"
        )


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_code_fence(raw_text: str) -> str:
    """Unwrap a ```json ... ``` fence some models wrap JSON in.

    This is formatting cleanup, not leniency about content: the unwrapped
    text still has to pass strict JSON + schema validation below. A response
    that doesn't match the fence pattern is passed through unchanged and
    left to fail json.loads on its own merits.
    """
    m = _FENCE_RE.match(raw_text.strip())
    return m.group(1) if m else raw_text


def parse_chapter_response(raw_text: str, *, valid_para_ids: set[int]) -> ChapterExtraction:
    """Strictly parse one chapter call's JSON response.

    Raises on anything malformed rather than applying a partial result -- a
    half-written chapter is worse than a failed one because the pass would
    silently move on and the gap would be invisible.
    """
    try:
        # strict=False: the digest_markdown value is a multi-line markdown document
        # and models don't always escape embedded newlines as \n. Every structural,
        # type, and citation check below still runs unchanged on the parsed object.
        obj = json.loads(_strip_code_fence(raw_text), strict=False)
    except json.JSONDecodeError as exc:
        raise ValueError(f"chapter response is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"chapter response must be a JSON object, got {type(obj).__name__}")

    digest_markdown = _require_str(obj, "digest_markdown", "chapter response")
    _validate_digest_markdown(digest_markdown, "chapter response", _CHAPTER_FRONT_MATTER_KEYS)

    raw_entities = obj.get("entities")
    if not isinstance(raw_entities, list):
        raise ValueError("chapter response: field 'entities' must be a list")

    entities: list[EntityRecord] = []
    for i, e in enumerate(raw_entities):
        where = f"chapter response entities[{i}]"
        if not isinstance(e, dict):
            raise ValueError(f"{where}: must be an object")
        designator = _require_str(e, "designator", where)
        node_kind = _require_str(e, "node_kind", where)
        if node_kind not in _VALID_NODE_KINDS:
            raise ValueError(f"{where}: node_kind must be one of {_VALID_NODE_KINDS}, got {node_kind!r}")
        cite_para_id = _require_int(e, "cite_para_id", where)
        _require_cite(cite_para_id, valid_para_ids, where)

        attributes: list[EntityAttributeRecord] = []
        for j, a in enumerate(e.get("attributes", [])):
            awhere = f"{where}.attributes[{j}]"
            if not isinstance(a, dict):
                raise ValueError(f"{awhere}: must be an object")
            attr_kind = _require_str(a, "attr_kind", awhere)
            value = _require_str(a, "value", awhere)
            a_cite = _require_int(a, "cite_para_id", awhere)
            _require_cite(a_cite, valid_para_ids, awhere)
            attributes.append(EntityAttributeRecord(attr_kind=attr_kind, value=value, cite_para_id=a_cite))

        aliases: list[EntityAliasRecord] = []
        for j, al in enumerate(e.get("aliases", [])):
            alwhere = f"{where}.aliases[{j}]"
            if not isinstance(al, dict):
                raise ValueError(f"{alwhere}: must be an object")
            other_designator = _require_str(al, "other_designator", alwhere)
            edge_type = _require_str(al, "edge_type", alwhere)
            if edge_type not in _VALID_EDGE_TYPES:
                raise ValueError(f"{alwhere}: edge_type must be one of {_VALID_EDGE_TYPES}, got {edge_type!r}")
            al_cite = _require_int(al, "cite_para_id", alwhere)
            _require_cite(al_cite, valid_para_ids, alwhere)
            aliases.append(
                EntityAliasRecord(other_designator=other_designator, edge_type=edge_type, cite_para_id=al_cite)
            )

        entities.append(
            EntityRecord(
                designator=designator,
                node_kind=node_kind,
                cite_para_id=cite_para_id,
                attributes=attributes,
                aliases=aliases,
            )
        )

    return ChapterExtraction(digest_markdown=digest_markdown, entities=entities)


def parse_rollup_response(raw_text: str) -> str:
    """Strictly parse a rollup call's JSON response, returning the digest markdown body."""
    try:
        obj = json.loads(_strip_code_fence(raw_text), strict=False)
    except json.JSONDecodeError as exc:
        raise ValueError(f"rollup response is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"rollup response must be a JSON object, got {type(obj).__name__}")

    digest_markdown = _require_str(obj, "digest_markdown", "rollup response")
    _validate_digest_markdown(digest_markdown, "rollup response", _ROLLUP_FRONT_MATTER_KEYS)
    return digest_markdown
