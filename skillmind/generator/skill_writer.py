"""
skillmind.generator.skill_writer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM-agnostic SKILL.md generator. Three tiers:
  1. No backend  → skeleton SKILL.md (always works, zero API key)
  2. Anthropic   → full Claude draft
  3. OpenAI-compat → Azure / Ollama / any OpenAI-compatible endpoint
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from skillmind.analyzer.patterns import CommandPattern, ToolSequencePattern

SYSTEM_PROMPT = """You are SkillMind, an expert at writing Claude Code SKILL.md files.
Output ONLY the raw markdown. No preamble, no explanation.

Structure:
---
name: <short skill name>
triggers: [<phrase1>, <phrase2>]
---

## When to use
<1-2 sentences>

## Steps
<numbered steps>

## Example
<concrete example>

## Notes
<caveats or context>
"""


def _skeleton(name: str, triggers: str, seen: str, body: str) -> str:
    return f"""---
name: {name}
triggers: [{triggers}]
---

## When to use
<!-- TODO: describe when to apply this skill -->
Observed {seen}.

## Steps
{body}

## Example
<!-- TODO: add a concrete example -->

## Notes
<!-- TODO: add caveats or context -->
"""


def skill_skeleton_from_command(pattern: CommandPattern) -> str:
    intent_comment = ""
    if pattern.intent_snippets:
        lines = "\n".join(f"  - {s}" for s in pattern.intent_snippets[:3])
        intent_comment = f"\n<!-- Observed context:\n{lines}\n-->"
    return _skeleton(
        name=f"{pattern.command.split()[0].capitalize()} workflow",
        triggers=f'"{pattern.command}", "run {pattern.command.split()[0]}"',
        seen=f"{pattern.count}× across {len(pattern.sessions)} sessions{intent_comment}",
        body=f"1. \n2. \n3. \n\n```bash\n{pattern.command}\n```",
    )


def skill_skeleton_from_sequence(pattern: ToolSequencePattern) -> str:
    steps = "".join(f"{i+1}. {t}\n" for i, t in enumerate(pattern.sequence))
    return _skeleton(
        name=f"{pattern.sequence[0].capitalize()} sequence",
        triggers=f'"{pattern.sequence[0].lower()}"',
        seen=f"{pattern.count}× across {len(pattern.sessions)} sessions",
        body=steps,
    )


class LLMBackend(ABC):
    @abstractmethod
    def complete(self, user_prompt: str) -> str: ...


class AnthropicBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("Run: uv add anthropic")
        self._client = __import__("anthropic").Anthropic(api_key=api_key)
        self.model = model

    def complete(self, user_prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=self.model, max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text


class OpenAICompatibleBackend(LLMBackend):
    def __init__(self, base_url: str, api_key: str = "ollama", model: str = "llama3"):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("Run: uv add openai")
        self._client = __import__("openai").OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def complete(self, user_prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
        )
        return resp.choices[0].message.content


def detect_backend() -> LLMBackend | None:
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicBackend(api_key=key)
    if key := os.environ.get("OPENAI_API_KEY"):
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("SKILLMIND_MODEL", "gpt-4o-mini")
        return OpenAICompatibleBackend(base_url=base, api_key=key, model=model)
    if url := os.environ.get("SKILLMIND_OLLAMA"):
        model = os.environ.get("SKILLMIND_MODEL", "llama3")
        return OpenAICompatibleBackend(base_url=url, api_key="ollama", model=model)
    return None


def skill_from_command_pattern(pattern: CommandPattern,
                                backend: LLMBackend | None = None) -> tuple[str, bool]:
    if backend is None:
        return skill_skeleton_from_command(pattern), False
    intent_block = ""
    if pattern.intent_snippets:
        snippets = "\n".join(f"  - {s}" for s in pattern.intent_snippets[:3])
        intent_block = (
            f"\n\nContext in which this command appeared (sampled from real sessions):\n{snippets}"
        )
    prompt = (
        f"Command `{pattern.command}` was used {pattern.count} times across "
        f"{len(pattern.sessions)} Claude Code sessions.{intent_block}\n\n"
        f"Draft a SKILL.md teaching when and how to use it."
    )
    return backend.complete(prompt), True


def skill_from_sequence_pattern(pattern: ToolSequencePattern,
                                 backend: LLMBackend | None = None) -> tuple[str, bool]:
    if backend is None:
        return skill_skeleton_from_sequence(pattern), False
    prompt = (
        f"Tool sequence {pattern.label} repeated {pattern.count} times across "
        f"{len(pattern.sessions)} sessions. Draft a SKILL.md for this workflow."
    )
    return backend.complete(prompt), True


def write_skill_file(content: str, output_dir: Path, name: str) -> Path:
    slug = name.lower().replace(" ", "_").replace("/", "_").strip("_")
    path = output_dir / slug / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
