"""The Chrome extension as a download (decision 91): extension/ → scudi-snai-extension.zip at the site's root, one folder
`scudi-snai-extension/` inside, files in a fixed order with a fixed date, so the zip only changes when a file does.

    python3 tools/pack_extension.py         # rebuild the zip after changing anything in extension/
    python3 tools/pack_extension.py --check # exit 1 if the zip is out of date (the tests run this)
"""

from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "extension"
OUT = ROOT / "scudi-snai-extension.zip"
FOLDER = "scudi-snai-extension"


def build() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in SRC.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"{FOLDER}/{f.relative_to(SRC).as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, f.read_bytes())
    return buf.getvalue()


def main(argv: list[str]) -> int:
    data = build()
    if "--check" in argv:
        ok = OUT.exists() and OUT.read_bytes() == data
        print("extension zip up to date" if ok else "extension zip OUT OF DATE: run python3 tools/pack_extension.py")
        return 0 if ok else 1
    OUT.write_bytes(data)
    print(f"{OUT.name}: {len(data) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
