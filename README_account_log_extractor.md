# Account Number Log Extraction Tool

A Python 3 command-line tool that scans a folder of daily application log
files, finds every occurrence of a given account number, and extracts the
**complete request** each occurrence belongs to — bounded by two fixed log
markers — into a single consolidated TXT file.

- Script: `account_log_extractor.py`
- Sample logs: `sample_logs/`
- Example output: `sample_logs/Extracted_Requests/Account_1234567890_Extracted_Requests.txt`

---

## 1. Assumptions about how requests are separated

The tool is built around these assumptions. If your logs differ, adjust the
markers (Section 6) — the algorithm itself stays correct.

1. **Every request is delimited by a pair of markers**, in order:
   - START: `-----ENTERIG TO DECRYPT TOKEN STARTS----`
   - END:   `USSDCustomMiddleware|user with Token`
2. **Requests do not nest.** One START is closed by the next END. A START
   seen while another request is still open means the earlier request never
   reached its END — it is treated as **incomplete**, not merged.
3. **A line "contains" a marker** if the marker text appears anywhere in the
   line (the marker need not be the whole line). This matches real logs where
   markers are preceded by a timestamp/level.
4. **The account number can appear anywhere inside the request** — not
   necessarily right after the START marker, and possibly on several lines.
5. **Account matching is exact for numeric tokens**: searching `1234567890`
   must not match `11234567890` or `12345678901`. The number is matched only
   when it is not flanked by other digits.
6. **File name order == chronological order.** Date-stamped daily logs such as
   `application_2026-11-18.log` sort into correct date order, so files are
   processed alphabetically to preserve the original timeline.
7. **Anything outside a START…END block is not part of a request** and is
   ignored (headers, heartbeats, unrelated traffic).

---

## 2. How the extraction algorithm works

The core (`extract_requests_from_file`) is a **single-pass streaming state
machine**. It reads each file one line at a time and keeps only the *current*
request block in memory — never the whole file — which satisfies the
large-file / low-memory requirement.

State per file: `in_request`, a line `buffer`, and `account_seen`.

```
for each line in the file:
    if line contains START_MARKER:
        if a request was already open and its account matched:
            emit it as INCOMPLETE (missing end marker)   # never merge
        open a new block: buffer = [line], account_seen = (account in line)

    elif in_request:
        buffer.append(line)
        if account in line: account_seen = True
        if line contains END_MARKER:
            if account_seen: emit block as a COMPLETE match
            reset state (ready for the next request in the same file)

at end of file:
    if a request is still open and its account matched:
        emit it as INCOMPLETE (missing end marker)
```

Why this is correct and robust:

- **Request-boundary driven, not marker-global.** Matching is decided *per
  block*. This is equivalent to "find the account, then walk backwards to the
  nearest START and forwards to its END" — but done in one forward pass.
- **No duplicates.** `account_seen` is a single boolean per block, so an
  account appearing several times inside one request yields exactly **one**
  extraction (see Request 2 in the example — the number appears three times).
- **No merging.** Each START…END pair is its own block; a block is emitted and
  the state reset before the next block begins.
- **Incomplete handling.** A START with no matching END (because EOF arrived,
  or a new START appeared first) is reported in a clearly separated
  *Incomplete Requests* section rather than being silently dropped or fused
  with the next request.
- **Order preserved.** Lines are buffered and written verbatim, and files are
  processed in sorted (chronological) order, so the output mirrors the logs.

### Error handling built in

Invalid/empty folder, empty account number, no matching log files, empty log
files, unreadable/locked files, missing START or END markers, and odd file
encodings are all handled with clear messages — a single bad file never aborts
the whole run. Files are opened with `errors="replace"` so a stray byte in an
otherwise-text log cannot crash the tool. Source logs are opened read-only and
are never modified.

---

## 3. Running the tool

Requires only Python 3.6+ and the standard library.

### Interactive mode (matches the required UX)

**Linux / macOS**
```bash
python3 account_log_extractor.py
```

**Windows**
```bat
python account_log_extractor.py
```

You will be prompted for the account number and the log folder path, e.g.:
```
Enter Account Number: 1234567890
Enter Log Folder Path: C:\ApplicationLogs
```

### Non-interactive mode (scriptable / for automation)

Supply the same values as flags to skip the prompts:

**Linux / macOS**
```bash
python3 account_log_extractor.py --account 1234567890 --folder /var/log/myapp
```

**Windows**
```bat
python account_log_extractor.py --account 1234567890 --folder C:\ApplicationLogs
```

### Choosing which file extensions count as logs

Default is `.log` and `.txt`. Override with a comma-separated list:

```bash
python3 account_log_extractor.py -a 1234567890 -f ./sample_logs -e ".log,.txt,.out"
```

---

## 4. Where the output goes

The tool creates (if needed) an `Extracted_Requests` folder **inside the log
folder you supplied**, and writes one consolidated file:

```
<your-log-folder>/Extracted_Requests/Account_<ACCOUNT_NUMBER>_Extracted_Requests.txt
```

A file is **always** produced — even when there are zero matches — so you
always have a record of the search.

---

## 5. Try it with the included sample

```bash
python3 account_log_extractor.py --account 1234567890 --folder sample_logs
```

The three sample files deliberately exercise the tricky cases:

| File | What it tests |
|------|---------------|
| `application_2026-11-18.log` | A plain match; plus `9999999999` and `11234567890` which must **not** be picked up (exact-match guard). |
| `application_2026-11-19.log` | The account appears **three times in one request** — must extract **once** (no duplicates). |
| `application_2026-11-20.log` | A START with the account but **no END** before the next START — reported as **incomplete**. |

Expected result: **2 complete matches**, **1 incomplete**, and the
`11234567890` / `9999999999` blocks correctly ignored. See
`sample_logs/Extracted_Requests/Account_1234567890_Extracted_Requests.txt`.

---

## 6. Changing the markers (if the log format changes)

Open `account_log_extractor.py` and edit the constants near the top of the
**CONFIGURATION** section — these are the only values you normally touch:

```python
START_MARKER = "-----ENTERIG TO DECRYPT TOKEN STARTS----"
END_MARKER   = "USSDCustomMiddleware|user with Token"
```

Replace the strings with your new boundary text. Matching is a plain
substring check (`marker in line`), so:

- Put the **exact** marker text here, including punctuation and spacing.
- No regex escaping is required — these are literal strings.

Related knobs in the same section:

```python
DEFAULT_EXTENSIONS = (".log", ".txt")   # which files are scanned by default
OUTPUT_DIR_NAME    = "Extracted_Requests"
FILE_ENCODING      = "utf-8"            # change if your logs use another encoding
ENCODING_ERRORS    = "replace"          # how to handle undecodable bytes
```

If your account numbers can contain non-digit characters and you need a
different boundary rule, change the pattern in `build_account_matcher()`
(currently `(?<![0-9]) … (?![0-9])`, which enforces exact numeric matching).
