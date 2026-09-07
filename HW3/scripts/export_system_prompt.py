"""Export systémového promptu z HW1 pro .NET klienta.

Python klient si prompt importuje přímo; C# na balíček z HW1 nedosáhne.
Exportuje se šablona se zástupnými znaky `{today}`, `{weekday}`, `{month}`
plus české názvy dnů — datum dosazuje klient sám.

    python scripts/export_system_prompt.py          # zapíše agents/system_prompt.json
    python scripts/export_system_prompt.py --check  # jen ověří, že je aktuální
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "HW1" / "src"))

from timeagent.agent import _WEEKDAYS, SYSTEM_PROMPT

TARGET = Path(__file__).resolve().parents[1] / "agents" / "system_prompt.json"

PAYLOAD = {
    "_comment": (
        "Generováno skriptem HW3/scripts/export_system_prompt.py z "
        "HW1/src/timeagent/agent.py. Needituj ručně — změny patří do HW1."
    ),
    "template": SYSTEM_PROMPT,
    "weekdays": list(_WEEKDAYS),
}


def render() -> str:
    return json.dumps(PAYLOAD, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Nepřepisuj, jen ohlas, jestli se soubor liší od HW1",
    )
    args = parser.parse_args()

    wanted = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != wanted:
            print(
                f"{TARGET.name} je zastaralý proti HW1 — spusť "
                "`python scripts/export_system_prompt.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET.name} odpovídá HW1.")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(wanted, encoding="utf-8")
    print(f"Zapsáno: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
