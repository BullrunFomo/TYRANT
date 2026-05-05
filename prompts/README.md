# TYRANT Prompts

Source of truth for every AI prompt the bot uses. The runtime loader in
`pulse/ai/prompts.py` parses these markdown files at startup. Editing a file
here changes behavior immediately on next load.

## File format

Each prompt is one markdown file with two parts:

1. **YAML frontmatter** between `---` delimiters at the top — sets
   `model`, `temperature`, `max_tokens`, `response_format`.
2. **Body** — markdown with `# System` and `# User` sections. Each section's
   text is sent as a separate role in the chat completion request.

```markdown
---
id: naming
model: anthropic/claude-haiku-4.5
temperature: 0.8
max_tokens: 250
response_format:
  type: json_object
---

# System
You are ...

# User
Title: {{title}}
```

## Templating

- `{{var}}` is substituted with the value the calling code passes for that
  key. Missing keys raise a clear error.
- `{{include: shared/file.md}}` inlines another prompt file (relative to
  `prompts/`). Useful for shared style guides.

## Model overrides

The `model` value in frontmatter is the default. The calling code may pass an
override (typically the value of `OPENROUTER_MODEL_*` from `pulse/config.py`)
so model choice can be tuned via `.env` without editing the prompt file.

## Layout

```
prompts/
  README.md                       this file
  shared/
    pumpfun_style_guide.md        included by naming + description
  naming.md                       name, ticker, twitter_query rewrite
  description.md                  on-chain description copywrite
  quality_gate.md                 vision-based launchability score (currently disabled)
```

## Conventions

- One prompt per task. Don't pack multiple decisions into one call.
- Always ask for JSON output (`response_format: {type: json_object}`) and
  document the schema in the prompt body — the loader does not enforce a
  schema, the calling module validates after parse.
- System prompts are stable; user templates carry per-call data.
- Keep system prompts under ~500 tokens — most providers don't cache below
  their minimum threshold and the cost difference is negligible.
