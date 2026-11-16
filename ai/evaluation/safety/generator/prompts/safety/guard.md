---
id: safety/guard
version: 1
model_role: redteam_guard
description: The user turn for Llama Guard (flag-only pre-check of red-team candidates); OpenRouter adds Llama Guard's own classification template
inputs: [conversation]
---
# user
{{ conversation }}
