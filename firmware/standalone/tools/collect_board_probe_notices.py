"""Collect public source notices for the generic diagnostic review archive."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def collect(idf: Path, out: Path) -> list[dict]:
    project = Path(__file__).resolve().parents[1] / "board_probe/PROJECT-MIT-LICENSE.txt"
    required = [
        idf / "LICENSE",
        idf / "components/freertos/FreeRTOS-Kernel/LICENSE.md",
        idf / "components/freertos/FreeRTOS-Kernel/include/freertos/FreeRTOS.h",
        project,
    ]
    if not all(path.is_file() for path in required):
        raise ValueError("required project/IDF/FreeRTOS notice missing")
    # Over-inclusive public IDF component notices; not a linked-component claim.
    sources = {
        p
        for p in (idf / "components").rglob("*")
        if p.is_file() and p.name.lower().startswith(("license", "notice", "copying", "copyright"))
    }
    sources.update(required[:-1])
    if any(not path.resolve().is_relative_to(idf.resolve()) for path in sources):
        raise ValueError("notice escaped public IDF checkout")
    out.mkdir(exist_ok=False)
    inventory = []
    pairs = [(project, Path("PROJECT-MIT-LICENSE.txt"))]
    pairs += [
        (p, Path("ESP-IDF-LICENSE") if p == idf / "LICENSE" else p.relative_to(idf))
        for p in sorted(sources)
    ]
    for source, relative in pairs:
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inventory.append(
            {"path": relative.as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        )
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    inventory = collect(args.idf, args.out)
    print(f"Collected {len(inventory)} public notices; no device access")


if __name__ == "__main__":
    main()
