---
id: description
model: anthropic/claude-haiku-4.5
temperature: 0.9
max_tokens: 250
response_format:
  type: json_object
---

# System

{{include: shared/pumpfun_style_guide.md}}

Write the on-chain `description` for a pump.fun memecoin. 1–2 sentences,
200 chars max. Capture the joke. Sound like a degen wrote it. The chosen
on-chain name and ticker are given — match their tone.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{"description": "..."}

Constraints (validated; failing output is rejected):
- description: 10–200 chars, no URLs, no emojis, no `\n` linebreaks

# User

Token name: {{name}}
Ticker: {{ticker}}
Source meme title: {{title}}
KYM blurb: {{kym_description}}
