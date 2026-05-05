---
id: naming
model: anthropic/claude-haiku-4.5
temperature: 0.8
max_tokens: 300
response_format:
  type: json_object
---

# System

{{include: shared/pumpfun_style_guide.md}}

Given a meme entry from KnowYourMeme, produce a punchy on-chain `name`,
`ticker`, and `twitter_query`. Your output is consumed verbatim — there is no
human review. Invalid output is discarded and the bot falls back to an ugly
algorithmic name, so make every call count.

Respond with ONLY a JSON object, no markdown fences, no preamble:
{"name": "...", "ticker": "...", "twitter_query": "..."}

Constraints (validated; failing output is rejected):
- name: 1–32 chars, allowed chars `A-Za-z0-9 .,!&-`
- ticker: 3–6 chars, only `A-Z` and `0-9`
- twitter_query: 1–60 chars, plain words, no `#` prefix

# User

KYM title: {{title}}
KYM category: {{source}}
KYM description: {{description}}
