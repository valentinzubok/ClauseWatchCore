"""Pytest bootstrap: mock the GenVM `genlayer` module so the contract can be imported."""

from __future__ import annotations

import sys
import types
from pathlib import Path


def _install_fake_genlayer() -> None:
    existing = sys.modules.get("genlayer")
    if existing is not None and getattr(existing, "_clausewatch_fake", False):
        return

    gl = types.ModuleType("genlayer")
    gl._clausewatch_fake = True

    class _Public:
        @staticmethod
        def write(fn):
            return fn

        @staticmethod
        def view(fn):
            return fn

    class _EqPrinciple:
        @staticmethod
        def prompt_comparative(leader_fn, principle=""):
            return leader_fn()

        @staticmethod
        def strict_eq(leader_fn):
            return leader_fn()

    # GenVM v0.3 API surface used by the contract.
    gl.contract = types.SimpleNamespace(Contract=object)
    gl.public = _Public()
    gl.eq_principle = _EqPrinciple()
    gl.message = types.SimpleNamespace(
        sender_address="0x1111111111111111111111111111111111111111"
    )
    # Tests drive these two: pages[url] is what validators "fetch",
    # verdict is what the validators' LLM returns.
    gl.pages = {}
    gl.verdict = '{"material": true}'

    def _render(url, mode="text"):
        if url not in gl.pages:
            raise Exception("404")
        return gl.pages[url]

    def _exec_prompt(prompt, response_format=None):
        return gl.verdict

    gl.nondet = types.SimpleNamespace(
        web=types.SimpleNamespace(render=_render),
        exec_prompt=_exec_prompt,
    )
    sys.modules["genlayer"] = gl


def load_contract(repo_root: Path, filename: str = "ClauseWatch.py"):
    _install_fake_genlayer()
    path = repo_root / "contracts" / filename
    text = path.read_text(encoding="utf-8")
    module = types.ModuleType(f"contract_{filename.replace('.', '_')}")
    exec(compile(text, str(path), "exec"), module.__dict__)
    sys.modules[module.__name__] = module
    return module
