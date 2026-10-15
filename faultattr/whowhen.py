"""
Who&When (Zhang et al., ICML 2025) Hand-Crafted subset: loading and norms.

Integrity rules, enforced here rather than by convention:
  1. The Magentic-One norms (faultattr/norms/magentic_one.md) were frozen,
     and hashed into magentic_one.lock.json, BEFORE any failure record was
     downloaded. verify_norms() refuses to continue if the file's hash no
     longer matches.
  2. load_hand_crafted() refuses to use a data cache downloaded before the
     freeze time. The ordering "norms first, data second" is checkable from
     the two timestamps.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORMS = os.path.join(ROOT, "faultattr", "norms", "magentic_one.md")
LOCK = os.path.join(ROOT, "faultattr", "norms", "magentic_one.lock.json")
DATA_DIR = os.path.join(ROOT, "data", "who_and_when", "Hand-Crafted")
DATA_META = os.path.join(DATA_DIR, "_download.json")
HF_BASE = ("https://huggingface.co/datasets/Kevin355/Who_and_When/resolve/main/"
           + urllib.parse.quote("Who&When/Hand-Crafted/"))
N_CASES = 58
AGENTS = ["Orchestrator", "WebSurfer", "FileSurfer", "Coder",
          "ComputerTerminal"]


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


NORMS_DIR = os.path.join(ROOT, "faultattr", "norms")
# v1: frozen before any record was downloaded. v2 / v3: post-hoc variants of
# v1, frozen after the pilot, each differing from v1 by one stated edit.
NORMS_VERSIONS = {"v1": "magentic_one", "v2": "magentic_one_v2",
                  "v3": "magentic_one_v3",
                  # rule-count experiment (PREREG_rulecount_20261002.md):
                  # granularity-only derivations of v1
                  "nbal": "magentic_one_nbal", "norch": "magentic_one_norch",
                  "nweb": "magentic_one_nweb"}


def norms_path(version: str = "v1") -> str:
    return os.path.join(NORMS_DIR, NORMS_VERSIONS[version] + ".md")


def lock_path(version: str = "v1") -> str:
    return os.path.join(NORMS_DIR, NORMS_VERSIONS[version] + ".lock.json")


def verify_norms(version: str = "v1") -> dict:
    """Return the lock if the norms file is unchanged; else SystemExit."""
    path = NORMS if version == "v1" else norms_path(version)
    lp = LOCK if version == "v1" else lock_path(version)
    if not os.path.exists(lp):
        raise SystemExit(f"norms {version} were never frozen (no lock "
                         f"file); refusing")
    lock = json.load(open(lp, encoding="utf-8"))
    now = _sha(open(path, "rb").read())
    if now != lock["sha256"]:
        raise SystemExit(f"NORMS {version} CHANGED since freeze: lock "
                         f"{lock['sha256']} != current {now}. Refusing.")
    if version != "v1":
        v1 = json.load(open(LOCK, encoding="utf-8"))
        if lock.get("derived_from_sha256") != v1["sha256"]:
            raise SystemExit(f"norms {version} not derived from the frozen "
                             f"v1; refusing")
    print(f"norms {version} verified  sha256={now}  frozen_at="
          f"{lock['frozen_at']}" + ("" if version == "v1" else
                                    f"  (post-hoc: {lock['edit']})"))
    return lock


def norms_text(version: str = "v1") -> str:
    path = NORMS if version == "v1" else norms_path(version)
    return open(path, encoding="utf-8").read()


def rules_blocks(version: str = "v1") -> str:
    """Only the per-agent RULES sections, without sources or preamble."""
    t = norms_text(version)
    parts = re.findall(r"^## (\w+)\n\nRULES:\n(.*?)(?=\n## |\Z)", t, re.S | re.M)
    return "\n\n".join(f"{name} RULES:\n{body.strip()}" for name, body in parts)


def load_hand_crafted(lock: dict) -> List[dict]:
    """All 58 Hand-Crafted records, downloading once into data/."""
    frozen = datetime.fromisoformat(lock["frozen_at"])
    if os.path.exists(DATA_META):
        meta = json.load(open(DATA_META, encoding="utf-8"))
        got = datetime.fromisoformat(meta["downloaded_at"])
        if got <= frozen:
            raise SystemExit(f"data was downloaded at {got}, not after the "
                             f"norms freeze at {frozen}; refusing")
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        meta = {"downloaded_at":
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": HF_BASE, "norms_sha256_at_download": lock["sha256"],
                "files": {}}
        for i in range(1, N_CASES + 1):
            req = urllib.request.Request(f"{HF_BASE}{i}.json",
                                         headers={"User-Agent": "faultattr"})
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
            with open(os.path.join(DATA_DIR, f"{i}.json"), "wb") as f:
                f.write(b)
            meta["files"][str(i)] = _sha(b)
        json.dump(meta, open(DATA_META, "w", encoding="utf-8"), indent=2)
    cases = []
    for i in range(1, N_CASES + 1):
        b = open(os.path.join(DATA_DIR, f"{i}.json"), "rb").read()
        if _sha(b) != meta["files"][str(i)]:
            raise SystemExit(f"cached case {i} changed since download")
        rec = json.loads(b)
        rec["_case"] = i
        cases.append(rec)
    return cases
