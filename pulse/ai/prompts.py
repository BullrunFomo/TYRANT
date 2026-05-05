"""Prompt loader — parses `prompts/*.md` (YAML frontmatter + # System / # User sections).

Resolves `{{include: shared/file.md}}` once at load time and `{{var}}` placeholders
at render time. The on-disk files in `prompts/` are the source of truth — change
them and the next call reflects the change (no rebuild).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent / "prompts"

_INCLUDE_RE = re.compile(r"\{\{\s*include:\s*([^}\s]+)\s*\}\}")
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_SECTION_RE = re.compile(r"^#\s+(System|User)\s*$", re.MULTILINE)


@dataclass
class Prompt:
    id: str
    model: str
    temperature: float
    max_tokens: int
    response_format: Optional[dict]
    multimodal: bool
    system_template: str
    user_template: str

    def render(self, **kwargs) -> tuple[str, str]:
        return _substitute(self.system_template, kwargs), _substitute(self.user_template, kwargs)


def load_prompt(name: str) -> Prompt:
    """Load `prompts/<name>.md`. Resolves includes immediately, defers vars to render()."""
    path = PROMPTS_ROOT / f"{name}.md"
    raw = path.read_text(encoding="utf-8")

    if not raw.startswith("---"):
        raise ValueError(f"Prompt '{name}': missing YAML frontmatter")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Prompt '{name}': malformed frontmatter")

    fm = yaml.safe_load(parts[1]) or {}
    body = _resolve_includes(parts[2], PROMPTS_ROOT)
    system, user = _split_sections(body)

    return Prompt(
        id=fm.get("id", name),
        model=str(fm.get("model", "")),
        temperature=float(fm.get("temperature", 0.7)),
        max_tokens=int(fm.get("max_tokens", 300)),
        response_format=fm.get("response_format"),
        multimodal=bool(fm.get("multimodal", False)),
        system_template=system.strip(),
        user_template=user.strip(),
    )


def _resolve_includes(text: str, root: Path, _depth: int = 0) -> str:
    if _depth > 5:
        raise ValueError("Prompt include depth exceeded — possible cycle")

    def repl(match):
        rel = match.group(1).strip()
        target = (root / rel).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            raise ValueError(f"Include escapes prompts/: {rel}")
        if not target.exists():
            raise FileNotFoundError(f"Prompt include not found: {rel}")
        return _resolve_includes(target.read_text(encoding="utf-8"), root, _depth + 1)

    return _INCLUDE_RE.sub(repl, text)


def _substitute(template: str, vars: dict) -> str:
    def repl(match):
        key = match.group(1)
        if key not in vars:
            raise KeyError(f"Prompt variable missing: '{key}'")
        return str(vars[key])
    return _VAR_RE.sub(repl, template)


def _split_sections(body: str) -> tuple[str, str]:
    """Split body on `# System` / `# User` headers (h1 only)."""
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return "", body
    sections = {"System": "", "User": ""}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[m.group(1)] = body[m.end():end]
    return sections["System"], sections["User"]
