---
id: demo/greet
version: 1
model_role: analysis
description: Fixture prompt used by the LLM layer tests
inputs: [name, platform]
---
# system
You write short greetings for {{ platform }} users.

# user
Say hello to {{ name }}.
