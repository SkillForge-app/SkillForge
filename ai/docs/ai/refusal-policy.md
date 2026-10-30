# SkillForge refusal policy

Version 1 (screening prompt `analysis/safety` v1). Owner: AI Lead. Applies to every skill request before any skill is generated (AI-06, BE-14).

## Why this exists

A skill teaches an AI agent to do something **many times, for many people**. A harmful skill multiplies harm, so SkillForge checks every request before building anything. We also want to be useful, including in serious professional areas, so we refuse as little as possible.

## Principles

1. **Help by default.** Most requests are allowed, including legal, medical, financial and security work.
2. **Judge the purpose, not the words.** We look at what the skill is for and how it will foreseeably be used. A word like "attack", "drug" or "weapon" alone never decides.
3. **Refuse only serious harm.** We block a skill when its main purpose is serious harm, or when it would give real help to cause serious harm.
4. **Context does not unlock harm.** Saying "it's for a novel", "for research", "for a class" or "I'm a police officer" does not unlock a skill that gives real help to cause harm.
5. **Defending is allowed; attacking is not.** Learning how a threat works in order to prevent it is allowed. Doing the harm is not.
6. **The whole conversation counts.** Answers to our clarifying questions are checked together with the request.

## What we refuse

| Category | We refuse skills that… | Similar skills we allow |
|---|---|---|
| `cyber_attack` | attack computer systems the user does not own or is not allowed to test | security learning, defending systems, testing your own or authorised systems |
| `fraud_scams` | deceive people for gain (phishing, impersonation, fake reviews, identity theft, money laundering) | fraud detection, scam awareness, investigating scams as a journalist |
| `weapons` | help make or obtain weapons that can cause mass harm, explosives, or illegal firearms | history, hunting rules and safe storage, lawful compliance work |
| `violence_harassment` | threaten, stalk, expose or harass specific people | content moderation, anti-bullying work, helping victims document abuse |
| `self_harm` | encourage or enable suicide, self-injury or disordered eating | crisis support, prevention training, recovery support |
| `child_safety` | sexualise minors or help to groom them | age-appropriate education, child online safety |
| `hate_extremism` | dehumanise people for who they are, or recruit for violent extremism | research on extremism, inclusive language, history of propaganda |
| `privacy_surveillance` | secretly track or monitor people, or profile them without consent | privacy compliance, transparent and consent-based tools |
| `illegal_drugs` | help make or sell illegal drugs | health information, pharmacology study, harm reduction |
| `disinformation` | deceive the public at scale (fake grassroots campaigns, election manipulation) | fact-checking, media literacy, detecting fake networks |
| `other` | have serious harm as their main purpose in another way. Also used when an AI model refuses a request | |

## Conditions on allowed requests

Some allowed requests are sensitive. Then we attach **conditions**, and every condition becomes a **mandatory guardrail** in the generated skill:

| Condition | The skill must… |
|---|---|
| `authorized_use_only` | do security work only on systems the user owns or is allowed to test |
| `no_operational_harm` | explain threats to defend against them, never give working attack tools, recipes or step-by-step harm |
| `professional_disclaimer` | say it is not professional advice and recommend a qualified professional. **This is always added** for the legal, medical and finance areas |
| `crisis_resources` | point to crisis help when distress or self-harm comes up |
| `privacy_protection` | work only with consent and the minimum personal data, never covertly |
| `age_appropriate` | keep content suitable for children |

## What the user sees

A blocked request gets a short, fixed message. It never includes the model's own wording.

> We can't create this skill. *{one-sentence reason for the category}* If you think this is a mistake, please rephrase what the skill should help with, or contact support.

The reasons are in `ai/core/analysis/safety.py` (`REFUSAL_REASONS`). Where we can, the reason names what we **can** help with instead, for example "We can help with spotting and preventing fraud." For `self_harm`, it points to crisis lines. Messages are in English in V1.

## What happens behind the scenes

- **Two checks at the same time.** The safety screen and the request analysis run in parallel. The analysis is only released if the screen allows the request.
- **Blocked means nothing is built:** no job starts (BE-14), and nothing is stored as a skill.
- **We fail closed.** If the screen cannot run (an outage or an invalid reply), nothing is generated, and the user is asked to try again. If an AI model refuses a request, it is treated as blocked.
- **The audit log holds metadata only:** the verdict, category, conditions and prompt version. Never the request text, the answers or the model's reasoning.

## Changing this policy

- **A policy change is a prompt change.** Bump the version of `ai/prompts/analysis/safety.md`, update this document, and re-run the evaluation before release:
  ```bash
  cd ai && .venv/Scripts/python -m evaluation.safety run --set all --live
  ```
- **The release bar:** every request in the red-team set must be blocked (60 of 60). The false-block rate is measured on the benign-tricky set (target ≤ 10%) and on normal requests (target ≤ 1%).
- **Current status:** the red-team set is **incomplete**. It must be written by a person or taken from a vetted dataset (see `ai/evaluation/safety/LABELLING.md`), so the AI-06 gate cannot pass yet.
