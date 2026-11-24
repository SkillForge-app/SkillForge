# AI-15: wording-only SkillSpec refinement

## Scope and acceptance

AI-15 refines ordinary wording in the `ai-engineer`, `marketing-strategist`, and `review-nda`
SkillSpecs. The canonical examples in `examples/skillspec/` remain unchanged; the proposed edited
copies are kept as validation fixtures in `tests/fixtures/ai15/`.

The AI refiner is an explicit step after Backend compilation. It sends each compiled Markdown
artifact to the wording prompt, stages all results separately, and publishes the output directory
only when the package check passes. Non-Markdown files are copied byte-for-byte. The check requires:

- The same package files, frontmatter presence and keys, and unchanged frontmatter values except
  `description`.
- The same headings in the same order, fenced code blocks, inline code, path literals, commands,
  link targets, and list structure.
- Descriptions within the platform's `PLATFORM_LIMITS` and no XML-like tags in visible prose.
- No output directory when any invariant fails.

The checker lives in `evaluation/ai15_package_check.py`. It shares the XML-tag rule with
`core/spec/validator.py` through `contains_xml_tag`; it does not duplicate that rule.
Code, Markdown autolinks, and generic type notation are excluded from the visible-prose XML scan.

## Reproducible check

Compile the pre-refinement and refined SkillSpecs with the Backend compiler pinned to commit
`af265589004bc070fbe0e3e9dfba9114ad32d211` (`abdo/skillspec-compiler`). That pinned compiler
commit is not reproducible from the current `main` branch until BE-09 lands. Place each compiled
skill package under its own directory, then run the refiner separately for Claude and Codex:

```powershell
python -m evaluation.ai15_refiner `
  --before C:\path\to\claude\ai-engineer `
  --after C:\path\to\claude\ai-engineer-refined `
  --platform claude `
  --live
```

`--live` permits real, paid model calls; the CLI refuses them unless this flag is present. Use it
only after cost approval. The command writes to a new output directory and refuses to overwrite
one. To compare previously compiled package trees without running the refiner:

```powershell
python -m evaluation.ai15_package_check `
  --before C:\path\to\packages-before `
  --after C:\path\to\packages-after
```

The comparison baseline used the original SkillSpecs from AI branch commit
`95a2da28bf3fe87ace57578a130a7d13d6eb3b9c`; edited examples are test fixtures and not canonical
source files.

## Verification

- Unit tests exercise the prompt, fixture validation, the live-call guard, package output staging,
  invariant rejection, and the CLI/checker paths. No live model calls are made by the tests.
- No paid refiner execution was run as part of this change.
- Earlier compiler verification passed for 23 compiled Claude and Codex files and 35 pinned
  Backend compiler tests; those results predate the integrated AI refiner.

This is the AI-owned interim package check, not a replacement for the Backend's future official
post-compilation package validator. Follow up by integrating that validator here when it is
available, while retaining the wording-only regression checks.
