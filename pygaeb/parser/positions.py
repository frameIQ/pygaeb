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
    names: list[str] = []
    # Per element: start line, start column, end line, end column, end byte index, parent.
    marks: list[list[int]] = []
    open_elements: list[int] = []
    # The encoding argument overrides the declaration: the bytes are UTF-8 whatever it says.
    # With "}" as separator a name reads "namespace}local", sliced like lxml's "{namespace}local".
    parser = xml.parsers.expat.ParserCreate(encoding="UTF-8", namespace_separator="}")

    def start(name: str, _attributes: object) -> None:
        parent = open_elements[-1] if open_elements else -1
        open_elements.append(len(marks))
        names.append(name)
        marks.append([parser.CurrentLineNumber, parser.CurrentColumnNumber, 0, 0, 0, parent])

    def end(_name: str) -> None:
        mark = marks[open_elements.pop()]
        mark[2:5] = [parser.CurrentLineNumber, parser.CurrentColumnNumber, parser.CurrentByteIndex]

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

    elements = [el for el in root.iter() if isinstance(el.tag, str)]
    if len(elements) != len(names):
        return {}, _MISALIGNED
    spans: dict[etree._Element, SourceSpan] = {}
    for element, name, mark in zip(elements, names, marks, strict=True):
        tag = str(element.tag)
        # "{namespace}Item" -> "Item"; slicing beats etree.QName on half a million elements.
        local = tag[tag.rfind("}") + 1:]
        written = name[name.rfind("}") + 1:]
        if (source_name(written) if source_name else written) != local:
            return {}, _MISALIGNED
        if local in wanted:
            line, column, end_line, end_column, end_byte, parent = mark
            # An empty-element tag right before its parent's end tag ends where the parent's does.
            if parent < 0 or marks[parent][4] != end_byte:
                end_line, end_column = _past_closing_tag(data, end_line, end_column, end_byte)
            spans[element] = SourceSpan(
                start_line=line, start_column=column + 1,
                end_line=end_line, end_column=end_column + 1,
            )
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
