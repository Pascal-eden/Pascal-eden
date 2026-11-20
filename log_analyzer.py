#!/usr/bin/env python3
"""
log_analyzer.py
===============

Recursively scan a folder of log files, search for one or more identifiers,
extract every matching log record together with its timestamp, and write a
readable ``.txt`` report.

Designed for investigating application, network, system and (authorized)
security logs. Uses only the Python standard library.

Author : senior-dev reference implementation
Python : 3.8+
License : MIT
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

logger = logging.getLogger("log_analyzer")


def configure_logging(verbose: bool = False) -> None:
    """Configure console logging for script execution and errors."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(handler)


# --------------------------------------------------------------------------- #
# Timestamp extraction engine (EXTENSIBLE)
# --------------------------------------------------------------------------- #
#
# To support a new timestamp format, append a ``TimestampPattern`` to
# ``TIMESTAMP_PATTERNS`` below. Order matters: the FIRST pattern that matches a
# line wins, so place more specific patterns before more general ones.
#
#   * ``regex``   : a compiled pattern whose match is the timestamp substring.
#   * ``formats`` : zero or more ``datetime.strptime`` format strings tried (in
#                   order) to turn the matched text into a ``datetime`` for
#                   *sorting only*. If none parse, the record is still kept; it
#                   simply sorts after records with parseable timestamps.
#   * ``preprocess`` : optional callable to normalise the matched text before
#                   parsing (e.g. strip a trailing ``Z``). Does NOT affect the
#                   value shown in the report.
#
# The displayed timestamp is ALWAYS the raw substring from the log — it is never
# reformatted or invented.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TimestampPattern:
    """A single recognizable timestamp format."""

    name: str
    regex: "re.Pattern[str]"
    formats: Tuple[str, ...] = ()
    preprocess: Optional[Callable[[str], str]] = None

    def parse(self, text: str) -> Optional[datetime]:
        """Return a ``datetime`` for sorting, or ``None`` if unparseable."""
        candidate = self.preprocess(text) if self.preprocess else text
        for fmt in self.formats:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
        return None


def _strip_zulu(text: str) -> str:
    """Normalise an ISO-8601 string so strptime can read it.

    Turns a trailing ``Z`` into ``+0000`` and removes the colon in the
    timezone offset (``+00:00`` -> ``+0000``) for ``%z`` compatibility.
    """
    out = text
    if out.endswith("Z"):
        out = out[:-1] + "+0000"
    # Collapse +HH:MM / -HH:MM offset into +HHMM for %z on older Pythons.
    out = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", out)
    return out


# Reusable sub-expressions.
_ISO_CORE = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
_FRACTION = r"(?:\.\d+)?"
_TZ = r"(?:Z|[+-]\d{2}:?\d{2})?"

TIMESTAMP_PATTERNS: List[TimestampPattern] = [
    # 2026-11-20T10:30:45.123Z  /  2026-11-20 10:30:45.123+01:00  (most specific)
    TimestampPattern(
        name="iso8601",
        regex=re.compile(_ISO_CORE + _FRACTION + _TZ),
        formats=(
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ),
        preprocess=_strip_zulu,
    ),
    # 20/11/2026 10:30:45  (day/month/year)
    TimestampPattern(
        name="dmy_slash",
        regex=re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}"),
        formats=("%d/%m/%Y %H:%M:%S",),
    ),
    # Nov 20 10:30:45  (syslog style, no year)
    TimestampPattern(
        name="syslog",
        regex=re.compile(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
            r"[ \d]\d \d{2}:\d{2}:\d{2}"
        ),
        # Year-less: the current year is injected for SORT ORDERING ONLY (the
        # displayed value remains the original, year-less string).
        formats=("%Y %b %d %H:%M:%S",),
        preprocess=lambda s: f"{datetime.now().year} {s}",
    ),
]


def extract_timestamp(line: str) -> Tuple[Optional[str], Optional[datetime]]:
    """Extract the first recognized timestamp from a line.

    Returns ``(raw_text, sort_key)``:
      * ``raw_text``  : the exact substring found in the log (``None`` if none).
      * ``sort_key``  : a ``datetime`` usable for sorting (``None`` if the text
                        could not be parsed, or none was found).
    """
    for pattern in TIMESTAMP_PATTERNS:
        match = pattern.regex.search(line)
        if match:
            raw = match.group(0)
            dt = pattern.parse(raw)
            # Normalise to a naive UTC datetime so timezone-aware and
            # timezone-naive values can be compared when sorting. This affects
            # only the sort key — never the displayed timestamp.
            if dt is not None and dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return raw, dt
    return None, None


# --------------------------------------------------------------------------- #
# Identifier matching
# --------------------------------------------------------------------------- #


def build_identifier_regexes(
    identifiers: Sequence[str],
    case_sensitive: bool,
    whole_word: bool,
) -> Dict[str, "re.Pattern[str]"]:
    """Compile one search pattern per identifier.

    ``whole_word=True`` (the default behaviour) performs *exact* matching: the
    identifier must not be flanked by word characters, so ``USER_123`` will not
    match inside ``USER_1234``. ``whole_word=False`` falls back to plain
    substring matching.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    regexes: Dict[str, "re.Pattern[str]"] = {}
    for ident in identifiers:
        escaped = re.escape(ident)
        if whole_word:
            # Lookarounds instead of \b so identifiers that start/end with
            # non-word characters still work.
            pattern = rf"(?<!\w){escaped}(?!\w)"
        else:
            pattern = escaped
        regexes[ident] = re.compile(pattern, flags)
    return regexes


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class MatchRecord:
    """A single matching log line."""

    identifier: str
    source_file: Path
    line_number: int
    timestamp_text: Optional[str]
    sort_key: Optional[datetime]
    record: str  # full, untruncated original line (newline stripped)


@dataclass
class ScanStats:
    """Aggregate counters for the run."""

    files_discovered: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    skipped_files: List[Tuple[Path, str]] = field(default_factory=list)
    matches_per_identifier: Dict[str, int] = field(default_factory=dict)

    @property
    def total_matches(self) -> int:
        return sum(self.matches_per_identifier.values())


# --------------------------------------------------------------------------- #
# File discovery & reading
# --------------------------------------------------------------------------- #


def discover_files(
    folder: Path,
    extensions: Sequence[str],
    exclude: Iterable[Path] = (),
) -> List[Path]:
    """Recursively find candidate log files, de-duplicated by resolved path.

    ``exclude`` lets us skip our own output file when it lives inside the scan
    folder.
    """
    normalized_exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    excluded_resolved = set()
    for p in exclude:
        try:
            excluded_resolved.add(p.resolve())
        except OSError:
            excluded_resolved.add(p.absolute())

    seen: set = set()
    files: List[Path] = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in normalized_exts:
            continue
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        if resolved in excluded_resolved or resolved in seen:
            continue
        seen.add(resolved)
        files.append(path)
    return files


def iter_lines(path: Path) -> Iterable[Tuple[int, str]]:
    """Yield ``(line_number, line)`` for a file, streaming line by line.

    Tries a sequence of encodings, finally falling back to a lossy decode so a
    few bad bytes never abort processing of an otherwise-readable file.
    """
    encodings = ("utf-8", "utf-8-sig", "latin-1")
    last_error: Optional[Exception] = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, errors="strict", newline="") as fh:
                for number, line in enumerate(fh, start=1):
                    yield number, line.rstrip("\n").rstrip("\r")
            return
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_error = exc
            continue  # try the next encoding
    # Final attempt: never fail on decoding — replace undecodable bytes.
    logger.debug("Falling back to lossy decode for %s (%s)", path, last_error)
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        for number, line in enumerate(fh, start=1):
            yield number, line.rstrip("\n").rstrip("\r")


# --------------------------------------------------------------------------- #
# Core scanning
# --------------------------------------------------------------------------- #


def scan_file(
    path: Path,
    identifier_regexes: Dict[str, "re.Pattern[str]"],
) -> List[MatchRecord]:
    """Scan a single file, returning every matching record (all occurrences)."""
    matches: List[MatchRecord] = []
    for number, line in iter_lines(path):
        # A line may contain several identifiers; record a match for each.
        for ident, regex in identifier_regexes.items():
            if regex.search(line):
                ts_text, sort_key = extract_timestamp(line)
                matches.append(
                    MatchRecord(
                        identifier=ident,
                        source_file=path,
                        line_number=number,
                        timestamp_text=ts_text,
                        sort_key=sort_key,
                        record=line,
                    )
                )
    return matches


def scan_folder(
    folder: Path,
    identifiers: Sequence[str],
    extensions: Sequence[str],
    case_sensitive: bool,
    whole_word: bool,
    output_path: Optional[Path] = None,
    progress: bool = True,
) -> Tuple[List[MatchRecord], ScanStats]:
    """Scan every eligible file under ``folder`` and collect matches + stats."""
    identifier_regexes = build_identifier_regexes(identifiers, case_sensitive, whole_word)

    exclude = [output_path] if output_path else []
    files = discover_files(folder, extensions, exclude=exclude)

    stats = ScanStats()
    stats.files_discovered = len(files)
    stats.matches_per_identifier = {ident: 0 for ident in identifiers}

    logger.info("Discovered %d candidate file(s).", stats.files_discovered)

    all_matches: List[MatchRecord] = []
    total = len(files)
    for index, path in enumerate(files, start=1):
        if progress:
            _print_progress(index, total, path)
        try:
            file_matches = scan_file(path, identifier_regexes)
        except (OSError, PermissionError) as exc:
            stats.files_skipped += 1
            stats.skipped_files.append((path, str(exc)))
            logger.warning("Skipping unreadable file %s: %s", path, exc)
            continue
        except Exception as exc:  # defensive: never abort the whole run
            stats.files_skipped += 1
            stats.skipped_files.append((path, repr(exc)))
            logger.warning("Skipping file after unexpected error %s: %s", path, exc)
            continue

        stats.files_processed += 1
        for record in file_matches:
            stats.matches_per_identifier[record.identifier] += 1
        all_matches.extend(file_matches)

    if progress and total:
        print("", file=sys.stderr)  # finish the progress line
    return all_matches, stats


def _print_progress(index: int, total: int, path: Path) -> None:
    """Render a single-line progress indicator on stderr."""
    pct = (index / total * 100) if total else 100.0
    name = path.name
    if len(name) > 40:
        name = "…" + name[-39:]
    sys.stderr.write(f"\r[{index}/{total}] {pct:5.1f}%  scanning {name:<40}")
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _sorted_matches(matches: List[MatchRecord]) -> List[MatchRecord]:
    """Sort matches chronologically, keeping unparseable timestamps last.

    Records with a parseable timestamp come first (ascending); records whose
    timestamp could not be parsed (or is absent) follow, in their original
    discovery order (stable sort).
    """
    return sorted(
        matches,
        key=lambda m: (m.sort_key is None, m.sort_key or datetime.max),
    )


def build_report(
    matches: List[MatchRecord],
    stats: ScanStats,
    folder: Path,
    identifiers: Sequence[str],
    case_sensitive: bool,
) -> str:
    """Produce the full human-readable report text."""
    lines: List[str] = []
    add = lines.append

    add("=" * 70)
    add("LOG IDENTIFIER SEARCH REPORT")
    add("=" * 70)
    add(f"Search Folder : {folder.resolve()}")
    add(f"Search Date   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    add(f"Identifiers   : {', '.join(identifiers)}")
    add(f"Case Sensitive: {'yes' if case_sensitive else 'no'}")
    add("")
    add("-" * 70)
    add("SUMMARY")
    add("-" * 70)
    add(f"Files discovered : {stats.files_discovered}")
    add(f"Files processed  : {stats.files_processed}")
    add(f"Files skipped    : {stats.files_skipped}")
    for ident in identifiers:
        add(f"Matches [{ident}] : {stats.matches_per_identifier.get(ident, 0)}")
    add(f"Total matches    : {stats.total_matches}")
    add("")

    if stats.skipped_files:
        add("-" * 70)
        add("FILES THAT COULD NOT BE PROCESSED")
        add("-" * 70)
        for path, reason in stats.skipped_files:
            add(f"  {path} -> {reason}")
        add("")

    # Group: identifier -> source file -> records.
    by_identifier: Dict[str, Dict[Path, List[MatchRecord]]] = {}
    for record in matches:
        by_identifier.setdefault(record.identifier, {}).setdefault(
            record.source_file, []
        ).append(record)

    for ident in identifiers:
        add("=" * 70)
        add(f"IDENTIFIER: {ident}")
        add("=" * 70)
        file_groups = by_identifier.get(ident)
        if not file_groups:
            add("  (no matches found)")
            add("")
            continue

        for source_file in sorted(file_groups, key=lambda p: str(p)):
            records = _sorted_matches(file_groups[source_file])
            add(f"  SOURCE FILE: {source_file.name}")
            add(f"  PATH       : {source_file.resolve()}")
            add("")
            for record in records:
                ts = record.timestamp_text if record.timestamp_text else "NOT FOUND"
                add(f"    Timestamp : {ts}")
                add(f"    Line      : {record.line_number}")
                add(f"    Log Record: {record.record}")
                add("")
    add("=" * 70)
    add("END OF REPORT")
    add("=" * 70)
    return "\n".join(lines) + "\n"


def build_records_only(matches: List[MatchRecord]) -> str:
    """Return just the matching log records, one per line, untruncated.

    Records are emitted in chronological order where timestamps can be parsed,
    with unparseable/timeless records kept last. Original content is preserved.
    """
    return "".join(f"{m.record}\n" for m in _sorted_matches(matches))


def write_report(report: str, output_path: Path) -> None:
    """Write the report to ``output_path`` (always UTF-8)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="log_analyzer.py",
        description="Recursively search log files for identifiers and extract "
        "matching records with timestamps.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--folder", type=str, help="Folder to scan recursively.")
    parser.add_argument(
        "--ids",
        nargs="+",
        metavar="ID",
        help="One or more identifiers to search for.",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output .txt report path.",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Make identifier matching case-sensitive (default: insensitive).",
    )
    parser.add_argument(
        "--substring",
        action="store_true",
        help="Match identifiers as substrings instead of exact whole tokens.",
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        default=[".log", ".txt"],
        metavar="EXT",
        help="Text-based extensions to scan.",
    )
    parser.add_argument(
        "--records-only",
        action="store_true",
        help="Output only the matching log records (no headers/timestamps/grouping).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the live progress indicator.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging.",
    )
    return parser.parse_args(argv)


def _prompt(message: str, default: Optional[str] = None) -> str:
    """Prompt the user, returning a stripped response (or the default)."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{message}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or (default or "")


def interactive_fill(args: argparse.Namespace) -> argparse.Namespace:
    """Fill any missing required values by prompting the user."""
    if not args.folder:
        args.folder = _prompt("Folder path to scan")
    if not args.ids:
        raw = _prompt("Identifier(s) to search (comma or space separated)")
        # Accept both comma- and space-separated input.
        args.ids = [tok for tok in re.split(r"[,\s]+", raw) if tok]
    if not args.output:
        args.output = _prompt("Output file path", default="log_search_results.txt")
    # Only prompt about case sensitivity when the flag wasn't explicitly set.
    if not args.case_sensitive:
        answer = _prompt("Case-sensitive search? (y/N)", default="n").lower()
        args.case_sensitive = answer in {"y", "yes"}
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(verbose=args.verbose)

    # If essential inputs are missing, drop into interactive prompts.
    if not (args.folder and args.ids and args.output):
        args = interactive_fill(args)

    if not args.folder or not args.ids:
        logger.error("A folder and at least one identifier are required.")
        return 2

    folder = Path(args.folder).expanduser()
    if not folder.exists():
        logger.error("Folder does not exist: %s", folder)
        return 2
    if not folder.is_dir():
        logger.error("Path is not a directory: %s", folder)
        return 2

    output_path = Path(args.output or "log_search_results.txt").expanduser()

    logger.info("Scanning %s for %d identifier(s).", folder, len(args.ids))
    matches, stats = scan_folder(
        folder=folder,
        identifiers=args.ids,
        extensions=args.ext,
        case_sensitive=args.case_sensitive,
        whole_word=not args.substring,
        output_path=output_path,
        progress=not args.no_progress,
    )

    if args.records_only:
        report = build_records_only(matches)
    else:
        report = build_report(
            matches=matches,
            stats=stats,
            folder=folder,
            identifiers=args.ids,
            case_sensitive=args.case_sensitive,
        )
    try:
        write_report(report, output_path)
    except OSError as exc:
        logger.error("Could not write report to %s: %s", output_path, exc)
        return 1

    # Console summary.
    logger.info("Files discovered: %d | processed: %d | skipped: %d",
                stats.files_discovered, stats.files_processed, stats.files_skipped)
    for ident in args.ids:
        logger.info("  %s: %d match(es)", ident, stats.matches_per_identifier.get(ident, 0))
    logger.info("Total matches: %d", stats.total_matches)
    logger.info("Report written to: %s", output_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
