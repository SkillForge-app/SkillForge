# AI-15: wording-only SkillSpec refinement

## Scope and acceptance

AI-15 refines ordinary wording in the `ai-engineer`, `marketing-strategist`, and `review-nda`
SkillSpecs. It does not change their structure. The package check compares the compiled artifacts
before and after refinement and requires:

- The same package files and frontmatter keys.
- The same headings in the same order, fenced code blocks, inline literals, paths, commands, link
  targets, and list structure.
- Non-Markdown artifacts to remain byte-for-byte identical; only prose and frontmatter
  `description` values may change.
- Generated descriptions to fit `PLATFORM_LIMITS`, with no XML-like tags in generated Markdown.

The checker lives in `evaluation/ai15_package_check.py`. It shares the XML-tag rule with
`core/spec/validator.py` through `contains_xml_tag`; it does not duplicate that rule.

## Reproducible check

Compile the pre-refinement and refined SkillSpecs with the Backend compiler pinned to commit
`af265589004bc070fbe0e3e9dfba9114ad32d211` (`abdo/skillspec-compiler`). Place the outputs under
matching `claude/<skill>/` and `codex/<skill>/` directories, then run:

```powershell
python -m evaluation.ai15_package_check `
  --before C:\path\to\packages-before `
  --after C:\path\to\packages-after
```

The comparison baseline used the original SkillSpecs from AI branch commit
`95a2da28bf3fe87ace57578a130a7d13d6eb3b9c`. The post-refinement side used the three SkillSpecs
in `examples/skillspec/`.

## Verified result

- `python -m core.spec validate` passed for all three refined SkillSpecs.
- The package checker passed for 23 compiled Claude and Codex files.
- The pinned Backend compiler tests passed: 35 tests collected and passed across its compiler,
  Claude artifact, snapshot, and Codex test modules.
- Focused local validator and package-check tests passed (29 total).

This is the AI-owned interim package check, not a replacement for the Backend's future official
post-compilation package validator. Follow up by integrating that validator here when it is
available, while retaining the wording-only regression checks.
