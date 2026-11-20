#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ACCOUNT NUMBER LOG EXTRACTION TOOL
==================================

Searches a folder of daily application log files for a specified account
number and extracts the *complete* request associated with each occurrence.

A "request" is the block of log lines bounded by two markers:

    START MARKER : -----ENTERIG TO DECRYPT TOKEN STARTS----
    END MARKER   : USSDCustomMiddleware|user with Token

All complete matching requests (and any incomplete ones) are written to a
single consolidated TXT file inside an ``Extracted_Requests`` folder created
in the supplied log directory.

Design goals:
    * Accuracy first  - extract the whole request, never just the line.
    * Streaming       - files are read line-by-line, never loaded whole.
    * Non-destructive - source log files are only ever read, never modified.

Author : Senior Python Developer
Python : 3.6+
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
# These are the ONLY things you normally need to change if the log format
# changes.  See the README for a full explanation.

# The exact substrings that bound a single request.  A line "contains" a
# marker if the marker text appears anywhere within the line.
START_MARKER = "-----ENTERIG TO DECRYPT TOKEN STARTS----"
END_MARKER = "USSDCustomMiddleware|user with Token"

# Default file extensions that are treated as log files.  Lower-case, with
# the leading dot.  Can be overridden on the command line with --extensions.
DEFAULT_EXTENSIONS = (".log", ".txt")

# Output folder (created inside the supplied log directory) and separator.
OUTPUT_DIR_NAME = "Extracted_Requests"
SEPARATOR = "=" * 70

# How we read files.  'replace' guarantees we never crash on a stray byte
# in an otherwise text log (handles "unexpected file encoding" gracefully).
FILE_ENCODING = "utf-8"
ENCODING_ERRORS = "replace"


# ---------------------------------------------------------------------------
# DATA MODEL
# ---------------------------------------------------------------------------
class ExtractedRequest:
    """A single request block extracted from one log file."""

    def __init__(self, source_file, start_line_no, lines, complete, reason=""):
        self.source_file = source_file      # filename the request came from
        self.start_line_no = start_line_no  # 1-based line of the START marker
        self.lines = lines                  # original log lines (with newline)
        self.complete = complete            # True if both markers were found
        self.reason = reason                # why it is incomplete, if so


# ---------------------------------------------------------------------------
# 1. USER INPUT
# ---------------------------------------------------------------------------
def print_header():
    """Display the application header."""
    print(SEPARATOR)
    print("          ACCOUNT NUMBER LOG EXTRACTION TOOL")
    print(SEPARATOR)
    print()


def prompt_account_number(preset=None):
    """
    Return a validated, non-empty account number.

    If ``preset`` is supplied (e.g. from the command line) it is used instead
    of prompting, which keeps the tool scriptable and testable.
    """
    if preset is not None:
        account = preset.strip()
        if not account:
            raise ValueError("Account number must not be empty.")
        return account

    while True:
        account = input("Enter Account Number: ").strip()
        if account:
            return account
        print("  [ERROR] Account number cannot be empty. Please try again.\n")


def prompt_folder_path(preset=None):
    """
    Return a validated folder path that exists and is a directory.

    If ``preset`` is supplied it is validated and returned without prompting.
    """
    if preset is not None:
        folder = os.path.expanduser(preset.strip().strip('"').strip("'"))
        _validate_folder(folder)
        return folder

    while True:
        folder = input("Enter Log Folder Path: ").strip().strip('"').strip("'")
        folder = os.path.expanduser(folder)
        try:
            _validate_folder(folder)
            return folder
        except (FileNotFoundError, NotADirectoryError) as exc:
            print(f"  [ERROR] {exc}\n")


def _validate_folder(folder):
    """Raise a descriptive error if ``folder`` is not a usable directory."""
    if not folder:
        raise FileNotFoundError("Folder path must not be empty.")
    if not os.path.exists(folder):
        raise FileNotFoundError(f"Folder does not exist: {folder}")
    if not os.path.isdir(folder):
        raise NotADirectoryError(f"Path is not a directory: {folder}")


# ---------------------------------------------------------------------------
# 2 & LOG FILE DISCOVERY
# ---------------------------------------------------------------------------
def discover_log_files(folder, extensions):
    """
    Return a sorted list of (filename, full_path) for readable log files.

    * Only files directly inside ``folder`` are considered (daily logs).
    * The ``Extracted_Requests`` output folder is skipped so previous output
      is never re-scanned.
    * Files are returned sorted by name so that, for date-stamped daily logs
      (e.g. application_2026-11-18.log), the original chronological order is
      preserved in the output.
    """
    extensions = tuple(e.lower() for e in extensions)
    found = []
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(name)[1].lower() not in extensions:
            continue
        found.append((name, full))
    return found


# ---------------------------------------------------------------------------
# 3. ACCOUNT MATCHING
# ---------------------------------------------------------------------------
def build_account_matcher(account_number):
    """
    Build a function that returns True when ``account_number`` appears in a
    line as a *whole* token, so that 1234567890 does not match 11234567890.

    We guard the number with negative look-behind/look-ahead for digits,
    which is the correct boundary rule for numeric account identifiers
    (a plain \\b would still treat a trailing letter as a boundary).
    """
    escaped = re.escape(account_number)
    pattern = re.compile(r"(?<![0-9])" + escaped + r"(?![0-9])")
    return pattern.search


# ---------------------------------------------------------------------------
# 4. REQUEST BOUNDARY IDENTIFICATION + EXTRACTION  (the core algorithm)
# ---------------------------------------------------------------------------
def extract_requests_from_file(filename, full_path, account_matches):
    """
    Stream a single log file and yield ExtractedRequest objects for every
    request block that contains the account number.

    The algorithm is a small state machine that walks the file once, in
    original order, keeping only the current request block in memory:

        * On a START marker  -> open a new block (buffering begins here).
          If a block was already open it means its END was never seen, so
          that previous block is flushed as INCOMPLETE (missing end marker)
          when it contained the account.
        * While a block is open -> buffer each line and remember whether the
          account number has appeared anywhere in the block so far.
        * On an END marker -> close the block.  If the account was seen in
          the block it is yielded as a COMPLETE matching request.
        * At end-of-file -> an open block whose account matched is yielded as
          INCOMPLETE (missing end marker).

    Because matching is decided per *block*, an account number that appears
    several times inside one request is extracted only once (no duplicates),
    and separate requests are never merged.
    """
    in_request = False
    buffer = []
    start_line_no = None
    account_seen = False

    try:
        fh = open(full_path, "r", encoding=FILE_ENCODING, errors=ENCODING_ERRORS)
    except (OSError, IOError) as exc:
        # Unreadable or locked file - report and skip without crashing.
        print(f"  [WARNING] Could not open '{filename}': {exc}")
        return

    with fh:
        for line_no, line in enumerate(fh, start=1):
            is_start = START_MARKER in line
            is_end = END_MARKER in line

            if is_start:
                # A new request begins.  If one was already open, it lacked
                # an end marker -> flush it as incomplete when it matched.
                if in_request and account_seen:
                    yield ExtractedRequest(
                        filename, start_line_no, buffer, complete=False,
                        reason="Missing end marker (new request started first)",
                    )
                in_request = True
                buffer = [line]
                start_line_no = line_no
                account_seen = bool(account_matches(line))
                continue

            if in_request:
                buffer.append(line)
                if account_matches(line):
                    account_seen = True
                if is_end:
                    # Request is complete.  Emit only if the account matched.
                    if account_seen:
                        yield ExtractedRequest(
                            filename, start_line_no, buffer, complete=True,
                        )
                    # Reset for the next request in the same file.
                    in_request = False
                    buffer = []
                    start_line_no = None
                    account_seen = False
            # Lines outside any request block (no open START) are ignored,
            # which is correct: a request is defined by its boundaries.

        # End of file reached with a block still open -> missing end marker.
        if in_request and account_seen:
            yield ExtractedRequest(
                filename, start_line_no, buffer, complete=False,
                reason="Missing end marker (end of file reached)",
            )


# ---------------------------------------------------------------------------
# 5. OUTPUT FILE GENERATION
# ---------------------------------------------------------------------------
def write_output(folder, account_number, complete_reqs, incomplete_reqs,
                 files_scanned):
    """
    Write every extracted request into one consolidated TXT file and return
    the output file path.  The file is always created, even when there are no
    matches, so the user always has a record of the search.
    """
    out_dir = os.path.join(folder, OUTPUT_DIR_NAME)
    os.makedirs(out_dir, exist_ok=True)

    # Keep the filename safe across OSes by stripping path separators.
    safe_account = re.sub(r"[^A-Za-z0-9_.-]", "_", account_number)
    out_name = f"Account_{safe_account}_Extracted_Requests.txt"
    out_path = os.path.join(out_dir, out_name)

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"ACCOUNT NUMBER: {account_number}\n")
        out.write(f"GENERATED: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        out.write(f"FILES SCANNED: {files_scanned}\n")
        out.write(f"TOTAL MATCHING REQUESTS: {len(complete_reqs)}\n")
        out.write(f"INCOMPLETE REQUESTS: {len(incomplete_reqs)}\n")

        if not complete_reqs and not incomplete_reqs:
            out.write("\n")
            out.write(SEPARATOR + "\n")
            out.write("NO MATCHING REQUESTS WERE FOUND FOR THIS ACCOUNT NUMBER.\n")
            out.write(SEPARATOR + "\n")
            return out_path

        # ---- Complete requests ------------------------------------------
        for index, req in enumerate(complete_reqs, start=1):
            out.write("\n")
            out.write(SEPARATOR + "\n")
            out.write(f"REQUEST {index}\n")
            out.write(f"SOURCE FILE: {req.source_file}\n")
            out.write(f"START LINE: {req.start_line_no}\n")
            out.write(SEPARATOR + "\n\n")
            # Preserve original content exactly - write lines verbatim.
            for line in req.lines:
                out.write(line if line.endswith("\n") else line + "\n")

        # ---- Incomplete requests (clearly separated) --------------------
        if incomplete_reqs:
            out.write("\n")
            out.write(SEPARATOR + "\n")
            out.write("INCOMPLETE REQUESTS (MARKER MISSING)\n")
            out.write(SEPARATOR + "\n")
            for index, req in enumerate(incomplete_reqs, start=1):
                out.write("\n")
                out.write(SEPARATOR + "\n")
                out.write(f"INCOMPLETE REQUEST {index}\n")
                out.write(f"SOURCE FILE: {req.source_file}\n")
                out.write(f"START LINE: {req.start_line_no}\n")
                out.write(f"REASON: {req.reason}\n")
                out.write(SEPARATOR + "\n\n")
                for line in req.lines:
                    out.write(line if line.endswith("\n") else line + "\n")

        out.write("\n")
        out.write(SEPARATOR + "\n")
        out.write("END OF EXTRACTION\n")

    return out_path


# ---------------------------------------------------------------------------
# 6. ORCHESTRATION
# ---------------------------------------------------------------------------
def run(account_number, folder, extensions):
    """Drive the full extraction workflow and print progress to the console."""
    print("\nInitializing search...\n")
    print("Scanning daily log files...\n")

    log_files = discover_log_files(folder, extensions)
    if not log_files:
        print(f"  [ERROR] No log files with extensions {extensions} "
              f"were found in: {folder}")
        # Still produce an (empty-result) output file for the record.
        out_path = write_output(folder, account_number, [], [], 0)
        _print_summary(account_number, 0, [], [], folder, out_path,
                       status="NO LOG FILES FOUND")
        return out_path

    for name, _ in log_files:
        print(f"[FOUND] {name}")

    print("\nSearching for matching requests...\n")

    account_matches = build_account_matcher(account_number)
    complete_reqs = []
    incomplete_reqs = []
    files_scanned = 0

    for name, full in log_files:
        files_scanned += 1
        # Guard per-file so one bad file never aborts the whole run.
        try:
            # Note empty files (handled naturally - they yield nothing).
            if os.path.getsize(full) == 0:
                print(f"  [SKIP] '{name}' is empty.")
            for req in extract_requests_from_file(name, full, account_matches):
                if req.complete:
                    complete_reqs.append(req)
                    print(f"[EXTRACTED] Request {len(complete_reqs)} - {name}")
                else:
                    incomplete_reqs.append(req)
                    print(f"[INCOMPLETE] {name} (line {req.start_line_no}) "
                          f"- {req.reason}")
        except Exception as exc:  # noqa: BLE001 - keep the tool resilient
            print(f"  [WARNING] Error while processing '{name}': {exc}")

    out_path = write_output(folder, account_number, complete_reqs,
                            incomplete_reqs, files_scanned)

    status = "SUCCESS" if complete_reqs else "NO MATCHING REQUESTS FOUND"
    _print_summary(account_number, files_scanned, complete_reqs,
                   incomplete_reqs, folder, out_path, status)
    return out_path


def _print_summary(account_number, files_scanned, complete_reqs,
                   incomplete_reqs, folder, out_path, status):
    """Print the final extraction summary block."""
    print()
    print(SEPARATOR)
    print("                  EXTRACTION SUMMARY")
    print(SEPARATOR)
    print()
    print(f"Account Number     : {account_number}")
    print(f"Files Scanned      : {files_scanned}")
    print(f"Matching Requests  : {len(complete_reqs)}")
    print(f"Incomplete Requests: {len(incomplete_reqs)}")
    print()
    print(f"Extraction Status  : {status}")
    print()
    print("Output Directory:")
    print(f"  {os.path.join(folder, OUTPUT_DIR_NAME)}")
    print()
    print("Output File:")
    print(f"  {os.path.basename(out_path)}")
    print()
    print(SEPARATOR)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------
def parse_args(argv):
    """Optional CLI arguments; when omitted the tool prompts interactively."""
    parser = argparse.ArgumentParser(
        description="Extract complete requests for an account number from "
                    "daily application log files.")
    parser.add_argument("-a", "--account", help="Account number to search for.")
    parser.add_argument("-f", "--folder", help="Folder containing log files.")
    parser.add_argument(
        "-e", "--extensions",
        help="Comma-separated list of log file extensions, "
             "e.g. '.log,.txt,.out'. Defaults to '.log,.txt'.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    print_header()

    try:
        account_number = prompt_account_number(args.account)
        folder = prompt_folder_path(args.folder)
    except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n[ABORTED] Input cancelled by user.")
        return 130

    if args.extensions:
        extensions = tuple(
            e if e.startswith(".") else "." + e
            for e in (x.strip().lower() for x in args.extensions.split(","))
            if e
        )
    else:
        extensions = DEFAULT_EXTENSIONS

    try:
        run(account_number, folder, extensions)
    except Exception as exc:  # noqa: BLE001 - final safety net
        print(f"[FATAL] Unexpected error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
