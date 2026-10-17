"""Kontrola modelu před startem klienta (M8, případ V28).

    uv run python check_model.py            # hodnoty z prostředí
    uv run python check_model.py --env ../HW2/.env

Porovná digest modelu `OLLAMA_MODEL` na serveru `OLLAMA_BASE_URL` s
`OLLAMA_MODEL_DIGEST`. Tag (`qwen2.5:32b`) je pohyblivý, digest ne: jiný
digest znamená jiný model, i když se jmenuje stejně. Při neshodě, chybějícím
digestu nebo nedostupném serveru končí kódem 1, klient se nemá spustit.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def check(base_url: str, model: str, expected: str) -> tuple[bool, str]:
    if not expected:
        return False, "OLLAMA_MODEL_DIGEST není nastavený"
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=10) as r:
        models = {m["name"]: m["digest"] for m in json.load(r)["models"]}
    actual = models.get(model)
    if actual is None:
        return False, f"model {model} na serveru není"
    if actual != expected:
        return False, f"{model}: digest {actual[:12]}… místo očekávaného {expected[:12]}…"
    return True, f"{model}: digest sedí ({actual[:12]}…)"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    env = dict(os.environ)
    if "--env" in sys.argv:
        env |= load_env(Path(sys.argv[sys.argv.index("--env") + 1]))
    try:
        ok, msg = check(env.get("OLLAMA_BASE_URL", ""), env.get("OLLAMA_MODEL", ""), env.get("OLLAMA_MODEL_DIGEST", ""))
    except OSError as e:
        ok, msg = False, f"server modelu nedostupný: {e}"
    print(("OK   " if ok else "STOP ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
