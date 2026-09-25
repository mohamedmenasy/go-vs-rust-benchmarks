"""Compile benchmark helper: rewrite one constant in a source file to a value
it has never had before (hyperfine --prepare step for the one-file-change
scenario).

A fresh value every time matters: Go's build cache is content-addressed, so
flipping between two values would be served from cache from the third build
on, while Cargo would recompile. The counter lives next to the file.

usage: edit_toggle.py FILE REGEX    (REGEX has exactly 3 groups; group 2 is
                                     replaced by the next counter value)
"""

import re
import sys
from pathlib import Path


def main() -> int:
    path, pattern = Path(sys.argv[1]), re.compile(sys.argv[2])
    counter = path.with_name(path.name + ".edit-counter")
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    src = path.read_text()
    new, k = pattern.subn(lambda m: f"{m[1]}{1000 + n}{m[3]}", src, count=1)
    if k != 1:
        print(f"edit_toggle: pattern not found in {path}", file=sys.stderr)
        return 1
    path.write_text(new)
    counter.write_text(str(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
