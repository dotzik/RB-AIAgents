"""Test mitigace M8: supply chain (kap. 4.4, případy V31–V37).

Statická kontrola repozitáře: co se při buildu a běhu stáhne, musí být
zamčené hashem nebo digestem. Test hlídá, aby se zámek při změně potichu
neztratil. Zda zámek obsahuje bezpečné verze, řeší audit (V27) v CI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted(ROOT.glob("HW*/**/Dockerfile"))
COMPOSE = sorted(ROOT.glob("HW*/docker-compose.yml"))
REQUIREMENTS = sorted(ROOT.glob("HW*/**/requirements.txt"))
CSPROJ = sorted(p for p in ROOT.glob("HW*/**/*.csproj") if "obj" not in p.parts)
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")
# CVE-2026-59951: stateful Streamable HTTP server neuvolní session (DoS),
# opraveno ve 2.2.0 a pro řadu 1.x v 1.30.0.
MCP_FIXED = {1: (1, 30, 0), 2: (2, 2, 0)}


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_v31_base_image_digestem():
    assert DOCKERFILES
    bad = [f"{_rel(df)}: {line}" for df in DOCKERFILES
           for line in df.read_text(encoding="utf-8").splitlines()
           if line.startswith("FROM ") and not DIGEST.search(line)]
    assert not bad, bad


def test_v32_compose_image_digestem():
    bad = [f"{_rel(c)}: {line.strip()}" for c in COMPOSE
           for line in c.read_text(encoding="utf-8").splitlines()
           if line.strip().startswith("image:") and not DIGEST.search(line)]
    assert not bad, bad


@pytest.mark.parametrize("req", REQUIREMENTS, ids=_rel)
def test_v33_requirements_s_hashi(req: Path):
    text = req.read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9_.\-\[\]]+)==\S+ \\\n((?:\s+--hash=sha256:[0-9a-f]{64}.*\n)+)", text, re.M)
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith((" ", "#"))]
    assert pins and len(pins) == len(lines), f"{_rel(req)}: řádek bez hashe"
    # Dockerfile vedle zámku ho musí vynutit.
    df = (req.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes" in df and "--no-deps" in df


def test_v34_mcp_bez_znamych_zranitelnosti():
    found = []
    for lock in [*REQUIREMENTS, *ROOT.glob("*/**/uv.lock"), ROOT / "security" / "uv.lock"]:
        text = lock.read_text(encoding="utf-8")
        found += re.findall(r'^mcp==([\d.]+)', text, re.M)
        found += re.findall(r'^name = "mcp"\nversion = "([\d.]+)"', text, re.M)
    assert found
    ver = [tuple(int(x) for x in v.split(".")) for v in found]
    old = [v for v in ver if v < MCP_FIXED.get(v[0], (0,))]
    assert not old, old


@pytest.mark.parametrize("proj", CSPROJ, ids=_rel)
def test_v35_nuget_jen_nugetorg_a_lockfile(proj: Path):
    assert "<RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>" in proj.read_text(encoding="utf-8-sig")
    lock = json.loads((proj.parent / "packages.lock.json").read_text(encoding="utf-8-sig"))
    assert lock["dependencies"]
    cfg = proj.parent.parent / "nuget.config"
    text = cfg.read_text(encoding="utf-8")
    assert "<clear />" in text
    assert re.findall(r'<add key="[^"]+" value="([^"]+)"', text) == ["https://api.nuget.org/v3/index.json"]
    assert '<package pattern="*" />' in text


def test_v36_n8n_bez_community_uzlu():
    text = (ROOT / "HW2" / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r'N8N_COMMUNITY_PACKAGES_ENABLED:\s*"false"', text)
    workflow = (ROOT / "HW2" / "scripts" / "build_n8n_workflow.py").read_text(encoding="utf-8")
    types = set(re.findall(r'"type":\s*"([^"]+\.[^"]+)"', workflow))
    assert types
    assert all(t.startswith(("n8n-nodes-base.", "@n8n/n8n-nodes-langchain.")) for t in types), types


def test_v37_vyjimky_auditu_platne():
    import tomllib
    from datetime import date

    exceptions = tomllib.loads((ROOT / "security" / "supply-chain-exceptions.toml").read_text(encoding="utf-8"))
    for e in exceptions.get("exception", []):
        assert e["reason"].strip() and e["fix"].strip() and e["owner"].strip() and e["ids"], e
        assert e["expires"] > date.today(), f"výjimka {e['package']} v {e['directory']} vypršela {e['expires']}"
        # Výjimka patří k jedné verzi. Po aktualizaci balíčku se musí smazat, ne zůstat viset.
        lock = (ROOT / e["directory"] / "uv.lock").read_text(encoding="utf-8")
        assert f'name = "{e["package"]}"\nversion = "{e["version"]}"' in lock, f"{e['package']} už není {e['version']}, výjimku smazat"
