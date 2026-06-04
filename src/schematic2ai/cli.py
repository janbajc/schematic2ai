"""
schematic2ai CLI.

Two invocation styles are supported (backwards-compatible):

1. **Convert a single schematic** (original behavior — no subcommand needed)::

       sch2ai INPUT [-o OUTPUT_DIR] [-f json|md|both] [--quiet]

   Produces::

       OUTPUT_DIR/<stem>.json
       OUTPUT_DIR/<stem>.md
       OUTPUT_DIR/<stem>_pages/*.png   (PDFs only)

2. **Diff two schematics** (new)::

       sch2ai diff OLD NEW [-o OUTPUT_DIR] [-f json|md|both] [--quiet]

   Produces::

       OUTPUT_DIR/<oldstem>__vs__<newstem>.diff.json
       OUTPUT_DIR/<oldstem>__vs__<newstem>.diff.md
       OUTPUT_DIR/<oldstem>_pages/*.png
       OUTPUT_DIR/<newstem>_pages/*.png

Output is deterministic and schema-stable so it can be safely piped into an LLM.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .parsers import parse, detect_parser
from .exporters import (
    export_json,
    export_markdown,
    export_diff_json,
    export_diff_markdown,
)
from .diff import diff_schematics


# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def _make_logger(quiet: bool):
    try:
        from rich.console import Console
        console = Console(quiet=quiet)
        return console.print
    except ImportError:
        def _log(*a, **_kw):
            if not quiet:
                print(*a)
        return _log


# ---------------------------------------------------------------------------
# Conversion core (default behavior)
# ---------------------------------------------------------------------------


def _run_convert(
    input_file: Path,
    output_dir: Path,
    fmt: str,
    quiet: bool,
) -> int:
    log = _make_logger(quiet)

    parser_cls = detect_parser(input_file)
    if parser_cls is None:
        click.echo(f"error: no parser found for {input_file}", err=True)
        return 2

    log(f"[bold]→[/bold] Detected format: [cyan]{parser_cls.format_name}[/cyan]")
    output_dir.mkdir(parents=True, exist_ok=True)
    schematic = parse(input_file, output_dir=output_dir)
    log(f"[bold]→[/bold] {schematic.summary()}")

    stem = input_file.stem
    written: list[Path] = []
    if fmt in ("json", "both"):
        written.append(export_json(schematic, output_dir / f"{stem}.json"))
    if fmt in ("md", "both"):
        written.append(export_markdown(schematic, output_dir / f"{stem}.md"))

    log("[bold green]✓ Wrote:[/bold green]")
    for p in written:
        log(f"   {p}")
    if schematic.images:
        log(f"[dim]+ {len(schematic.images)} image(s) bundled (paths recorded in output)[/dim]")
    if schematic.warnings:
        log(f"[yellow]⚠ {len(schematic.warnings)} warning(s) — see output file.[/yellow]")
    return 0


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.pass_context
def main(ctx: click.Context) -> None:
    """schematic2ai — convert schematics into AI-readable artifacts.

    Run ``sch2ai INPUT`` to convert a single file, or
    ``sch2ai diff OLD NEW`` to compare two schematics.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# `sch2ai convert`
# ---------------------------------------------------------------------------


@main.command("convert")
@click.argument(
    "input_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("out"),
    show_default=True,
    help="Directory where artifacts are written.",
)
@click.option(
    "-f", "--format", "fmt",
    type=click.Choice(["json", "md", "both"]),
    default="both",
    show_default=True,
    help="Which exporter(s) to run.",
)
@click.option("--quiet", is_flag=True, help="Suppress progress output.")
def convert_cmd(input_file: Path, output_dir: Path, fmt: str, quiet: bool) -> None:
    """Convert a single schematic INPUT_FILE into AI-readable artifacts."""
    code = _run_convert(input_file, output_dir, fmt, quiet)
    if code:
        sys.exit(code)


# ---------------------------------------------------------------------------
# `sch2ai diff OLD NEW`
# ---------------------------------------------------------------------------


@main.command("diff")
@click.argument(
    "old_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "new_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("out"),
    show_default=True,
    help="Directory where artifacts are written.",
)
@click.option(
    "-f", "--format", "fmt",
    type=click.Choice(["json", "md", "both"]),
    default="both",
    show_default=True,
    help="Which exporter(s) to run.",
)
@click.option("--quiet", is_flag=True, help="Suppress progress output.")
def diff_cmd(
    old_file: Path,
    new_file: Path,
    output_dir: Path,
    fmt: str,
    quiet: bool,
) -> None:
    """Diff two schematics (OLD_FILE vs NEW_FILE) into an AI-readable artifact.

    Both inputs are parsed into the IR (this also produces per-file JSON /
    Markdown / page images under OUTPUT_DIR), then a `SchematicDiff` is
    written alongside.
    """
    log = _make_logger(quiet)
    output_dir.mkdir(parents=True, exist_ok=True)

    old_parser = detect_parser(old_file)
    new_parser = detect_parser(new_file)
    if old_parser is None or new_parser is None:
        missing = old_file if old_parser is None else new_file
        click.echo(f"error: no parser found for {missing}", err=True)
        sys.exit(2)

    log(f"[bold]→[/bold] Parsing OLD: [cyan]{old_parser.format_name}[/cyan] {old_file}")
    old_sch = parse(old_file, output_dir=output_dir)
    log(f"[bold]→[/bold] {old_sch.summary()}")

    log(f"[bold]→[/bold] Parsing NEW: [cyan]{new_parser.format_name}[/cyan] {new_file}")
    new_sch = parse(new_file, output_dir=output_dir)
    log(f"[bold]→[/bold] {new_sch.summary()}")

    # Also emit per-side artifacts so the diff context is fully co-located.
    if fmt in ("json", "both"):
        export_json(old_sch, output_dir / f"{old_file.stem}.json")
        export_json(new_sch, output_dir / f"{new_file.stem}.json")
    if fmt in ("md", "both"):
        export_markdown(old_sch, output_dir / f"{old_file.stem}.md")
        export_markdown(new_sch, output_dir / f"{new_file.stem}.md")

    d = diff_schematics(old_sch, new_sch)
    log(f"[bold]→[/bold] {d.summary()}")

    diff_stem = f"{old_file.stem}__vs__{new_file.stem}.diff"
    written: list[Path] = []
    if fmt in ("json", "both"):
        written.append(export_diff_json(d, output_dir / f"{diff_stem}.json"))
    if fmt in ("md", "both"):
        written.append(export_diff_markdown(d, output_dir / f"{diff_stem}.md"))

    log("[bold green]✓ Wrote:[/bold green]")
    for p in written:
        log(f"   {p}")
    if d.warnings:
        log(f"[yellow]⚠ {len(d.warnings)} warning(s) — see output file.[/yellow]")


# ---------------------------------------------------------------------------
# Back-compat shim: `sch2ai PATH` (no subcommand) → `sch2ai convert PATH`.
# ---------------------------------------------------------------------------


_KNOWN_SUBCOMMANDS = {"convert", "diff"}


def _entrypoint() -> None:
    argv = sys.argv[1:]

    # Find the first non-flag token.
    first_positional = None
    for arg in argv:
        if arg.startswith("-"):
            continue
        first_positional = arg
        break

    if (
        first_positional is not None
        and first_positional not in _KNOWN_SUBCOMMANDS
        and Path(first_positional).is_file()
    ):
        # Legacy form: `sch2ai PATH [opts]` → inject ``convert``.
        sys.argv = [sys.argv[0], "convert", *argv]

    main()


if __name__ == "__main__":
    _entrypoint()
