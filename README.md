# Date-Based File Cleaner (GUI, Recursive)

A small, safe, and practical Tkinter GUI tool to **recursively scan a folder (including all subfolders)** and clean files by **date/time rules**. Designed for “click-and-run” usage: no terminal commands needed.

> Default behavior is conservative: **scan & preview first**, then **explicit confirmation** before any operation.

---

## Features

- **GUI-first workflow** (Tkinter): run the script and operate via buttons/inputs
- **Recursive scanning** of the selected folder (all subfolders included)
- Filter by file time:
  - `mtime` (modified time, recommended)
  - `ctime` (Windows ~ creation time; Linux = metadata change time)
- Date selection modes:
  - **on**: files within the selected day (00:00 to next day 00:00)
  - **before**: earlier than the selected day
  - **after**: on/after the selected day
  - **between**: range `[start, end)` (inclusive start, exclusive end)
- Optional wildcard filters:
  - **include** patterns (e.g., `*.png,*.txt`)
  - **exclude** patterns (e.g., `*.log,__pycache__*`)
- Safe actions:
  - **Trash mode (recommended):** move matched files to `_trash_YYYYMMDD_HHMMSS`
  - **Delete mode (dangerous):** permanent deletion with **double confirmation**
- Built-in preview list (to avoid UI freezing, only shows first N items; execution still processes all hits)
- Execution **does not close the app**: adjust options and run again

---

## Screenshot

Add your own screenshot here:

docs/screenshot.png

yaml
复制代码

Then reference it:

```markdown
![UI Screenshot](docs/screenshot.png)
Requirements
Python 3.8+ (recommended)

Tkinter (usually bundled with Python on Windows/macOS; on some Linux distros you may need to install it)

Tkinter on Linux (if missing)
Depending on your distro:

Debian/Ubuntu:

bash
复制代码
sudo apt-get install python3-tk
Fedora:

bash
复制代码
sudo dnf install python3-tkinter
Installation
Clone the repo:

bash
复制代码
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
No extra packages required.

Usage
Run the GUI:

bash
复制代码
python clean_by_date_ui.py
Typical workflow
Click “Browse…” to select the target folder

Choose:

time field: mtime (recommended) or ctime

mode: on / before / after / between

date(s): YYYY-MM-DD

(Optional) Set include/exclude wildcard patterns

Choose action:

Trash (recommended)

Delete (requires typing DELETE to confirm)

Click ① Scan Preview

Review preview list and summary

Click ② Execute and confirm

Safety Notes (Read This)
Trash mode is recommended: matched files are moved into a folder named _trash_YYYYMMDD_HHMMSS inside the selected root directory.

Delete mode is permanent:

You must confirm twice

You must type DELETE in all caps

By default, the scanner can skip _trash_* folders to prevent accidental repeated processing.

The app requires a new scan after execution, so you won’t accidentally “execute stale results.”

Time Field Explanation
mtime: last modified time
Best match for “files changed/produced on that date”

ctime:

Windows: often equals creation time

Linux/macOS: not strictly creation time; it is metadata status change time (e.g., permission change)

If your goal is “files created that day,” Windows users may prefer ctime. For cross-platform consistency, mtime is usually safer.

Wildcard Filters
Comma-separated patterns are supported.

Examples:

Include only images:

*.png,*.jpg,*.jpeg

Exclude logs and cache:

*.log,__pycache__*

Matching is applied to the filename (not full path), using standard shell-style wildcards.

Project Structure (Suggested)
text
复制代码
.
├─ clean_by_date_ui.py
├─ README.md
└─ docs/
   └─ screenshot.png
Roadmap (Optional Ideas)
Calendar date picker (no manual typing)

Per-item selection (checkboxes) in preview list

Search/sort in preview list (by size/path/time)

Export scan results to CSV

One-click “Restore from trash” helper

Contributing
PRs and issues are welcome.

When contributing:

Keep the tool safe by default

Avoid removing confirmations or preview steps

Prefer cross-platform behavior

License
Choose a license and add a LICENSE file.
Common options:

MIT (simple and permissive)

Apache-2.0 (permissive + patent grant)

GPL-3.0 (copyleft)

If you’re unsure: MIT is a solid default for small utilities.

Disclaimer
This tool can delete or move files. Use it at your own risk.
Always scan/preview before executing, and keep backups of important data.
