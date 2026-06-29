# SkillMind

> Detect reusable skills from your Claude Code sessions and turn them into `SKILL.md` files automatically.

## Install

```bash
git clone https://github.com/YOUR_USERNAME/skillmind
cd skillmind
uv sync
```

## Usage

```bash
# No API key needed — scan always works
uv run skillmind scan

# Skeleton SKILL.md files (no API key)
uv run skillmind suggest --output ./skills

# AI-drafted content — set one of:
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export SKILLMIND_OLLAMA=http://localhost:11434/v1

uv run skillmind suggest --output ./skills --top-n 5
```

## LLM backends

| Env var | Backend |
|---|---|
| `ANTHROPIC_API_KEY` | Claude (recommended) |
| `OPENAI_API_KEY` + `OPENAI_BASE_URL` | OpenAI or Azure |
| `SKILLMIND_OLLAMA` | Local Ollama |
| *(none)* | Skeleton mode — fully offline |

## License

MIT
