"""Exact source positions for parsed elements, counted the way an editor counts them.

lxml gives only a line, and libxml2 counts only LF as a line break, so a file with
CR line endings reports wrong lines. A second pass with the standard library's
expat parser reports line and column for every start tag. Both parsers see the
same elements in the same order, so the two lists line up by index.
"""

from __future__ import annotations

import xml.parsers.expat
from collections.abc import Callable, Collection

from lxml import etree

from pygaeb.models.source import SourceSpan

_MISALIGNED = "the second pass saw different elements"


class _EntityDeclared(Exception):
    """The file declares an entity: positions are skipped rather than the entity expanded."""


def element_spans(
    text: str,
    root: etree._Element,
    wanted: Collection[str],
    source_name: Callable[[str], str] | None = None,
) -> tuple[dict[etree._Element, SourceSpan], str | None]:
    """Spans for the elements of *root* whose local name is in *wanted*.

    *text* is the file as written (decoded, declaration untouched); *root* is the
    tree lxml built from it. *source_name* maps a tag name as written to the one
    lxml saw (the DA XML 2.x parser translates German names first). Returns the
    spans and ``None``, or no spans and the reason.
    """
    data = text.encode("utf-8")
    # Every element's name as written, in document order; expat interns the strings.
    names: list[str] = []
    # Name as written -> local name as lxml sees it.
    local_names: dict[str, str] = {}
    # Per wanted element only: start line, start column, end line, end column, end byte
    # index, and 1 when its parent's end tag follows it directly.
    marks: list[list[int]] = []
    open_marks: list[list[int] | None] = []
    last_ended: list[list[int] | None] = [None]
    # The encoding argument overrides the declaration: the bytes are UTF-8 whatever it says.
    # With "}" as separator a name reads "namespace}local", sliced like lxml's "{namespace}local".
    parser = xml.parsers.expat.ParserCreate(encoding="UTF-8", namespace_separator="}")

    def start(name: str, _attributes: object) -> None:
        names.append(name)
        local = local_names.get(name)
        if local is None:
            written = name[name.rfind("}") + 1:]
            local = local_names[name] = source_name(written) if source_name else written
        mark = None
        if local in wanted:
            mark = [parser.CurrentLineNumber, parser.CurrentColumnNumber, 0, 0, 0, 0]
            marks.append(mark)
        open_marks.append(mark)

    def end(_name: str) -> None:
        byte = parser.CurrentByteIndex
        # An empty-element tag ends just past its "/>": when the next end tag starts right
        # there, it is the parent's.
        previous = last_ended[0]
        if previous is not None and previous[4] == byte:
            previous[5] = 1
        mark = open_marks.pop()
        if mark is not None:
            mark[2:5] = [parser.CurrentLineNumber, parser.CurrentColumnNumber, byte]
        last_ended[0] = mark

    def refuse_entity(*_args: object) -> None:
        raise _EntityDeclared

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.EntityDeclHandler = refuse_entity
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except _EntityDeclared:
        return {}, "the file declares entities"
    except xml.parsers.expat.ExpatError as exc:
        return {}, f"the file is not well-formed XML ({exc})"

    # Walked lazily: a list of half a million element proxies cost about 50 MB.
    spans: dict[etree._Element, SourceSpan] = {}
    pending = iter(marks)
    tag_locals: dict[str, str] = {}
    count = 0
    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str):
            continue  # comments and processing instructions; expat reports no element
        if count == len(names):
            return {}, _MISALIGNED
        local = tag_locals.get(tag)
        if local is None:
            # "{namespace}Item" -> "Item"
            local = tag_locals[tag] = tag[tag.rfind("}") + 1:]
        if local_names[names[count]] != local:
            return {}, _MISALIGNED
        count += 1
        if local in wanted:
            line, column, end_line, end_column, end_byte, parent_follows = next(pending)
            if not parent_follows:
                end_line, end_column = _past_closing_tag(data, end_line, end_column, end_byte)
            spans[element] = SourceSpan(
                start_line=line, start_column=column + 1,
                end_line=end_line, end_column=end_column + 1,
            )
    if count != len(names):
        return {}, _MISALIGNED
    return spans, None


def _past_closing_tag(data: bytes, line: int, column: int, byte: int) -> tuple[int, int]:
    """Line and 0-based column just past the ``>`` that closes an element.

    expat reports an element's end at the ``<`` of its end tag, or just past the
    ``/>`` of an empty-element tag.
    """
    if not data.startswith(b"</", byte):
        return line, column
    tag = data[byte:data.index(b">", byte) + 1].decode("utf-8")
    # An end tag may break before its ">": "</Item\r\n  >".
    lines = tag.splitlines()
    if len(lines) == 1:
        return line, column + len(tag)
    return line + len(lines) - 1, len(lines[-1])
