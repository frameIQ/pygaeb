"""Command-line interface for pyGAEB.

Usage::

    pygaeb info tender.X83
    pygaeb validate tender.X83 --strict
    pygaeb convert old.D83 new.X83 --version 3.3
    pygaeb diff v1.X83 v2.X83
    pygaeb export tender.X83 -f xlsx -o report.xlsx
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pygaeb import __version__


@click.group()
@click.version_option(__version__, prog_name="pygaeb")
def main() -> None:
    """pyGAEB — Parse, validate, convert, and export GAEB DA XML files."""


@main.command()
@click.argument("file", type=click.Path(exists=True))
def info(file: str) -> None:
    """Show document information: version, phase, item count, totals."""
    from pygaeb import GAEBParser
    from pygaeb.models.enums import ValidationSeverity

    doc = GAEBParser.parse(file)
    items = list(doc.iter_items())
    errors = [
        r for r in doc.validation_results
        if r.severity == ValidationSeverity.ERROR
    ]
    warnings = [
        r for r in doc.validation_results
        if r.severity == ValidationSeverity.WARNING
    ]

    click.echo(f"File:      {Path(file).name}")
    click.echo(f"Version:   DA XML {doc.source_version.value}")
    click.echo(f"Phase:     {doc.exchange_phase.value}")
    click.echo(f"Kind:      {doc.document_kind.value}")
    click.echo(f"Items:     {len(items)}")

    if doc.is_procurement:
        click.echo(f"Currency:  {doc.award.currency}")
        if doc.grand_total:
            click.echo(f"Total:     {doc.grand_total:,.2f} {doc.award.currency}")
        if doc.award.project_no:
            click.echo(f"Project:   {doc.award.project_no}")
        if doc.award.project_name:
            click.echo(f"Name:      {doc.award.project_name}")

    if errors:
        click.echo(f"Errors:    {len(errors)}")
    if warnings:
        click.echo(f"Warnings:  {len(warnings)}")


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Fail on first ERROR-severity issue.")
def validate(file: str, strict: bool) -> None:
    """Validate a GAEB file and report issues."""
    from pygaeb import GAEBParser, ValidationMode
    from pygaeb.models.enums import ValidationSeverity

    mode = ValidationMode.STRICT if strict else ValidationMode.LENIENT
    try:
        doc = GAEBParser.parse(file, validation=mode)
    except Exception as e:
        click.echo(f"FAIL: {e}", err=True)
        sys.exit(1)

    if not doc.validation_results:
        click.echo("OK — no issues found.")
        sys.exit(0)

    severity_colors = {
        ValidationSeverity.ERROR: "red",
        ValidationSeverity.WARNING: "yellow",
        ValidationSeverity.INFO: "blue",
    }
    for r in doc.validation_results:
        prefix = click.style(
            f"[{r.severity.value}]",
            fg=severity_colors.get(r.severity, "white"),
        )
        click.echo(f"{prefix} {r.message}")

    errors = [
        r for r in doc.validation_results
        if r.severity == ValidationSeverity.ERROR
    ]
    if errors:
        sys.exit(1)


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", type=click.Path())
@click.option("--version", "target_version", default="3.3",
              type=click.Choice(["2.0", "2.1", "3.0", "3.1", "3.2", "3.3"]),
              help="Target DA XML version.")
@click.option("--phase", default=None, help="Override exchange phase (e.g., X84).")
def convert(input_file: str, output_file: str, target_version: str, phase: str | None) -> None:
    """Convert a GAEB file to a different DA XML version."""
    from pygaeb.converter import GAEBConverter
    from pygaeb.models.enums import ExchangePhase, SourceVersion

    version_map = {
        "2.0": SourceVersion.DA_XML_20, "2.1": SourceVersion.DA_XML_21,
        "3.0": SourceVersion.DA_XML_30, "3.1": SourceVersion.DA_XML_31,
        "3.2": SourceVersion.DA_XML_32, "3.3": SourceVersion.DA_XML_33,
    }
    tv = version_map[target_version]

    tp = None
    if phase:
        try:
            tp = ExchangePhase(phase)
        except ValueError:
            click.echo(f"Unknown phase: {phase}", err=True)
            sys.exit(1)

    report = GAEBConverter.convert(input_file, output_file, target_version=tv, target_phase=tp)
    click.echo(f"Converted {report.items_converted} items: "
               f"{report.source_version.value} -> {report.target_version.value}")
    if report.fields_dropped:
        for f in report.fields_dropped:
            click.echo(f"  Dropped: {f}")
    if report.warnings:
        for w in report.warnings:
            if "dropped" not in w.lower():
                click.echo(f"  Warning: {w}")


@main.command()
@click.argument("file_a", type=click.Path(exists=True))
@click.argument("file_b", type=click.Path(exists=True))
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]),
              help="Output format.")
def diff(file_a: str, file_b: str, fmt: str) -> None:
    """Compare two GAEB procurement documents."""
    from pygaeb.diff.boq_diff import BoQDiff
    from pygaeb.parser import GAEBParser

    doc_a = GAEBParser.parse(file_a)
    doc_b = GAEBParser.parse(file_b)

    try:
        result = BoQDiff.compare(doc_a, doc_b)
    except TypeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if fmt == "json":
        click.echo(result.model_dump_json(indent=2))
    else:
        s = result.summary
        click.echo(f"Changes: {s.total_changes} "
                    f"(added={s.items_added}, removed={s.items_removed}, "
                    f"modified={s.items_modified})")
        if s.financial_impact is not None:
            click.echo(f"Financial impact: {s.financial_impact:+,.2f}")
        if s.max_significance:
            click.echo(f"Max significance: {s.max_significance.value}")

        for added in result.items.added:
            click.echo(f"  + {added.oz}: {added.short_text}")
        for removed in result.items.removed:
            click.echo(f"  - {removed.oz}: {removed.short_text}")
        for modified in result.items.modified:
            click.echo(f"  ~ {modified.oz}: {len(modified.changes)} field(s) changed")


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-f", "--format", "fmt", default="json",
              type=click.Choice(["json", "csv", "xlsx"]),
              help="Export format.")
@click.option("-o", "--output", default=None, type=click.Path(),
              help="Output file path (default: derived from input).")
def export(file: str, fmt: str, output: str | None) -> None:
    """Export a GAEB file to JSON, CSV, or Excel."""
    from pygaeb import GAEBParser
    from pygaeb.convert import to_csv, to_json

    doc = GAEBParser.parse(file)
    stem = Path(file).stem

    if fmt == "json":
        out = output or f"{stem}.json"
        to_json(doc, out)
    elif fmt == "csv":
        out = output or f"{stem}.csv"
        to_csv(doc, out)
    elif fmt == "xlsx":
        from pygaeb.convert import to_excel
        out = output or f"{stem}.xlsx"
        to_excel(doc, out)
    else:
        click.echo(f"Unknown format: {fmt}", err=True)
        sys.exit(1)

    click.echo(f"Exported to {out}")
