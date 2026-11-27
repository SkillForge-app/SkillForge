# AI-10 chunk quality report (2026-11-25)

**Automatic gates: PASS.** **Human review: PENDING** until a person fills in the sample below (AI-10 is done at 18 or more good chunks out of 20).

Chunk settings: {"target_words": 180, "max_words": 250, "max_chars": 1800, "min_words": 50, "overlap_sentences": 2, "overlap_words": 40}. Extraction mode: precision. Site boilerplate removal: on (repeated sentences removed: www.ftc.gov 9).

## Automatic checks

| Check | Result | Gate |
|---|---|---|
| verdicts | 100.0% ✅ | ≥ 100% |
| titles | 100.0% ✅ | ≥ 100% |
| languages | 100.0% ✅ | ≥ 100% |
| facts | 100.0% ✅ | ≥ 95% |
| chunk_size | 100.0% ✅ | ≥ 90% |
| valid_passages | 100.0% ✅ | ≥ 100% |
| clean_ends | 99.6% ✅ | ≥ 95% |
| leaks | 0 ✅ | 0 |

## Pages

| Page | Expected | Got | Extractor | Words | Links | Chunks | Median / max words | Missing facts | Leaks | Top concepts |
|---|---|---|---|---|---|---|---|---|---|---|
| ftc-endorsement-faq.html | ok | ok ✅ | trafilatura | 14536 | 0.01 | 128 | 112.5 / 225 | – | – | disclosure, product, endorsement, review, company |
| ftc-can-spam.html | ok | ok ✅ | trafilatura | 2538 | 0.01 | 16 | 160 / 235 | – | – | message, can-spam act, recipient, email, commercial content |
| ftc-advertising-hub.html | ok | ok ✅ | trafilatura | 467 | 0.14 | 3 | 156 / 162 | – | – | advertising, children online privacy protection act, company, consumer, ftc |
| nist-ai-rmf.html | ok | ok ✅ | trafilatura | 319 | 0.18 | 2 | 159.5 / 193 | – | – | ai rmf, nist, public comment, ai product, ai program |
| google-seo-starter.html | ok | ok ✅ | trafilatura | 3342 | 0.05 | 29 | 119 / 201 | – | – | site, search result, page, content, google |
| google-helpful-content.html | ok | ok ✅ | trafilatura | 2170 | 0.02 | 16 | 144 / 229 | – | – | content, e-e-a-t, search engine, people-first content, main content |
| owasp-llm01.html | ok | ok ✅ | trafilatura | 1108 | 0.13 | 7 | 166 / 215 | – | – | model, prompt injection, scenario, attacker, prompt injection vulnerability |
| wikipedia-rag.html | ok | ok ✅ | trafilatura | 1542 | 0.06 | 13 | 114 / 194 | – | – | llm, rag, language model, retrieval-augmented generation, model |
| synthetic-subscriber-footer.html | ok | ok ✅ | trafilatura | 330 | 0.00 | 4 | 82 / 110 | – | – | form, people, clear email opt, subscriber, choice |
| synthetic-short-faq.html | ok | ok ✅ | trafilatura | 171 | 0.00 | 2 | 85.5 / 89 | – | – | gift card, card, card number, gift card faq, balance |
| synthetic-div-soup.html | ok | ok ✅ | trafilatura | 235 | 0.00 | 2 | 131.5 / 180 | – | – | user, change, added csv export service, breaking change, changelog page |
| synthetic-paywall-jsonld.html | paywall_or_login | paywall_or_login ✅ | trafilatura | 176 | 0.00 | 0 | – | – | – | – |
| synthetic-paywall-phrase.html | paywall_or_login | paywall_or_login ✅ | bs4 | 151 | 0.00 | 0 | – | – | – | – |
| synthetic-login-wall.html | paywall_or_login, too_short | paywall_or_login, too_short ✅ | trafilatura | 21 | 0.00 | 0 | – | – | – | – |
| synthetic-cookie-only.html | boilerplate, too_short | boilerplate, too_short ✅ | bs4 | 85 | 0.00 | 0 | – | – | – | – |
| synthetic-link-farm.html | boilerplate, too_short | boilerplate, too_short ✅ | bs4 | 15 | 0.88 | 0 | – | – | – | – |
| synthetic-stub.html | too_short | too_short ✅ | trafilatura | 36 | 0.00 | 0 | – | – | – | – |
| synthetic-js-shell.html | empty | empty ✅ | none | 0 | 0.00 | 0 | – | – | – | – |
| synthetic-french.html | wrong_language | wrong_language ✅ | trafilatura | 206 | 0.00 | 0 | – | – | – | – |
| synthetic-arabic.html | wrong_language | wrong_language ✅ | trafilatura | 157 | 0.00 | 0 | – | – | – | – |

## Human review: 20 sampled chunks

The sample is spread evenly over the 11 pages that have chunks: each page gets one chunk before any page gets a second (seed 7).

For each chunk, tick every box that holds, then mark it good only if all four do.
- **Stands alone:** makes sense without the chunks around it.
- **On topic:** about one subject, the one its section names.
- **No boilerplate:** no menus, cookie text, footers or ads.
- **Readable:** no broken sentences, glued words or stray markup.

Reviewer: ________  Date: ________  Good chunks: ____ / 20 (pass at 18)

### 1. `nist.gov-54dbc154-25768e49` (nist-ai-rmf.html, 126 words)

Section: (no heading)  
Concepts: ai rmf, ai product, ai program, ai rmf profile, ai-enabled capability

> On April 7, 2026, NIST released a concept note for an AI RMF Profile on Trustworthy AI in Critical Infrastructure. The profile will guide critical infrastructure operators towards specific risk management practices to consider when engaging AI-enabled capabilities.
> The AI RMF 1.0 is being revised as part of the White House AI Action Plan.
> Led by the Information Technology Laboratory (ITL) AI Program, and in collaboration with the private and public sectors, NIST has developed a framework to better manage risks to individuals, organizations, and society associated with artificial intelligence (AI). The NIST AI Risk Management Framework (AI RMF) is intended for voluntary use and to improve the ability to incorporate trustworthiness considerations into the design, development, use, and evaluation of AI products, services, and systems.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 2. `genai.owasp.org-742d684f-4d5c9bd8` (owasp-llm01.html, 116 words)

Section: Prevention and Mitigation Strategies  
Concepts: prevention and mitigation strategies, 4. enforce privilege control, access control, adversarial testing, breach simulation

> Prevention and Mitigation Strategies
> 4. Enforce privilege control and least privilege access
> Provide the application with its own API tokens for extensible functionality, and handle these functions in code rather than providing them to the model. Restrict the model’s access privileges to the minimum necessary for its intended operations.
> 5. Require human approval for high-risk actions
> Implement human-in-the-loop controls for privileged operations to prevent unauthorized actions.
> 6. Segregate and identify external content
> Separate and clearly denote untrusted content to limit its influence on user prompts.
> 7. Conduct adversarial testing and attack simulations\
> Perform regular penetration testing and breach simulations, treating the model as an untrusted user to test the effectiveness of trust boundaries and access controls.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 3. `developers.google.com-0af9dc7e-03a39f4f` (google-seo-starter.html, 144 words)

Section: Search Engine Optimization (SEO) Starter Guide › Help Google find your content  
Concepts: site, google, content, google search, page

> Help Google find your content
> Before you actually do anything mentioned in this section, check if Google has already found your content (maybe you don't need to do anything!). Try searching on Google for your site with the
> .
> If you see results pointing to your site, you're in the index. For example, a search for site: search operator
> site:wikipedia.org
> returns
> these results. If you don't see your site, check out the technical requirements to make sure there's nothing technically preventing your site from showing in Google Search, and then come back here.
> Google primarily finds pages through links from other pages it already crawled. In many cases, these are other websites that are linking to your pages. Other sites linking to you is something that happens naturally over time, and you can also encourage people to discover your content by promoting your site.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 4. `en.wikipedia.org-b43f8e16-53337ff0` (wikipedia-rag.html, 99 words)

Section: Improvements › Retriever-centric methods  
Concepts: retriever-centric method, document retrieval, generated response perplexity, generator model likelihood distribution, given prompt

> Retriever-centric methods
> These methods aim to enhance the quality of document retrieval in vector databases:
> - Pre-training the retriever using the Inverse Cloze Task (ICT), a technique that helps the model learn retrieval patterns by predicting masked text within documents.
> - Supervised retriever optimization aligns retrieval probabilities with the generator model's likelihood distribution. This involves retrieving the top-k vectors for a given prompt, scoring the generated response's perplexity, and minimizing KL divergence between the retriever's selections and the model's likelihoods to refine retrieval.
> - Reranking techniques can refine retriever performance by prioritizing the most relevant retrieved documents during training.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 5. `ftc.gov-5c252d1a-1a1a2d4e` (ftc-advertising-hub.html, 149 words)

Section: (no heading)  
Concepts: u.s. content, company, product, advertising claim, competent and reliable scientific evidence

> Companies are offering consumers an ever-growing assortment of “green” options. But whether your environmental claims are about the product or the packaging, you'll need competent and reliable scientific evidence to support what you say. Find out more by consulting the FTC’s revised Green Guides. Have you spotted what you think might be a deceptive claim or practice? File a complaint.
> Companies must support their advertising claims with solid proof. This is especially true for businesses that market food, over-the-counter drugs, dietary supplements, contact lenses, and other health-related products.
> Do you promote your products as “Made in the USA”? Under the law, some products must disclose U.S. content. For others, manufacturers and marketers who choose to make claims about the amount of U.S. content need to know about the FTC’s Made in USA Labeling Rule and Enforcement Policy Statement on U.S. Origin Claims. Is your company up on what's required?

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 6. `ftc.gov-629fbc85-245336c9` (ftc-endorsement-faq.html, 56 words)

Section: HOW SHOULD I DISCLOSE THAT I WAS GIVEN SOMETHING FOR MY ENDORSEMENT? › I have attended sneak peek events and use #comped or #hosted. Can influencers/bloggers use #comped and #hosted for non-paid endorsements?  
Concepts: non-paid endorsement, sneak peek event, brand, efg resort, example

> I have attended sneak peek events and use #comped or #hosted. Can influencers/bloggers use #comped and #hosted for non-paid endorsements?
> Neither #comped nor #hosted is sufficiently clear. It would be fine to say, for example, “XYZ brand flew me to Hawaii for their launch event at the EFG Resort,” assuming that is all the brand did.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 7. `developers.google.com-8d7d5b41-19ceeaab` (google-helpful-content.html, 154 words)

Section: Creating helpful, reliable, people-first content › Ask "Who, How, and Why" about your content  
Concepts: content, e-e-a-t, byline, accurate authorship information, author

> Ask "Who, How, and Why" about your content
> Consider evaluating your content in terms of "Who, How, and Why" as a way to stay on course with what our systems seek to reward.
> Who (created the content)
> Something that helps people intuitively understand the E-E-A-T of content is when it's clear who created it. That's the "Who" to consider. When creating content, here are some who-related questions to ask yourself:
> - Is it self-evident to your visitors who authored your content?
> - Do pages carry a byline, where one might be expected?
> - Do bylines lead to further information about the author or authors involved, giving background about them and the areas they write about?
> If you're clearly indicating who created the content, you're likely aligned with the concepts of E-E-A-T and on a path to success. We strongly encourage adding accurate authorship information, such as bylines to content where readers might expect it.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 8. `lanternbooks.example-ee6351af-955ee7a1` (synthetic-short-faq.html, 82 words)

Section: Gift Card FAQ › What happens if I lose my card?  
Concepts: gift card, card, card number, cash, new card

> What happens if I lose my card?
> Treat a gift card like cash. If you still have the receipt or the email with the card number, contact our shop team and we can move the remaining balance to a new card for you.
> Can I get a refund on a gift card?
> Gift cards cannot be exchanged for cash, but if a card was bought by mistake we can cancel it within 14 days as long as it has not been used.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 9. `northwind-notes.example-8fee64f3-32ff4174` (synthetic-subscriber-footer.html, 59 words)

Section: How to Write a Clear Email Opt-in Form › Ask only for what you need  
Concepts: email address, extra field, form, most newsletter, other detail

> Ask only for what you need
> Every extra field lowers the number of people who finish the form. For most newsletters an email address is enough at the start. If you want a first name for personalisation, make it optional and explain why you ask. Collect other details later, once the subscriber trusts you and can see the benefit.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 10. `shipwright.example-a339dbca-ef4df88e` (synthetic-div-soup.html, 180 words)

Section: (no heading)  
Concepts: change, user, added csv export service, breaking change, first line

> Most release notes are written for the team that shipped the change, not for the people who have to live with it. They list ticket numbers, internal code names and refactors that no user will ever notice, while the one change that breaks a workflow is buried in the middle.
> Start with the changes that require action. If a setting moved, an old behaviour was removed or an integration needs to be reconnected, say so in the first lines and explain what to do. Users forgive a breaking change much more easily when the notes tell them exactly how to adapt.
> Next, describe new features in terms of what users can now do, not what the team built. A sentence such as "you can now export reports as spreadsheets from the dashboard" is clearer than "added CSV export service". Link to a short guide when a feature needs more than two sentences.
> Group small fixes into a single list at the end and keep each item to one line. People scan this part, so plain words matter more than completeness.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 11. `ftc.gov-194ba0c8-92897893` (ftc-can-spam.html, 203 words)

Section: Q. What if the email includes information from more than one company? Who is the “sender” responsible for CAN-SPAM compliance?  
Concepts: sender, can-spam compliance, email, message, can-spam act

> Q. What if the email includes information from more than one company? Who is the “sender” responsible for CAN-SPAM compliance?
> A. If an email advertises or promotes the goods, services, or websites of more than one marketer, there’s a straightforward method for determining who’s responsible for the duties the CAN-SPAM Act imposes on “senders” of commercial email. Marketers whose goods, services, or websites are advertised or promoted in a message can designate one of the marketers as the “sender” for purposes of CAN-SPAM compliance as long as the designated sender:
> - meets the CAN-SPAM Act’s definition of “sender,” meaning that they initiate a commercial message advertising or promoting their own goods, services, or website;
> - is specifically identified in the “from” line of the message; and
> - complies with the “initiator” provisions of the Act – for example, making sure the email does not contain deceptive transmission information or a deceptive subject heading, and ensuring that the email includes a valid postal address, a working opt-out link, and proper identification of the message’s commercial or sexually explicit nature.
> If the designated sender doesn’t comply with the responsibilities the law gives to initiators, all marketers in the message may be held liable as senders.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 12. `nist.gov-54dbc154-0615c612` (nist-ai-rmf.html, 193 words)

Section: (no heading)  
Concepts: ai rmf, public comment, nist, ai risk management effort, ai rmf crosswalk

> Released on January 26, 2023, the Framework was developed through a consensus-driven, open, transparent, and collaborative process that included a Request for Information, several draft versions for public comments, multiple workshops, and other opportunities to provide input. It is intended to build on, align with, and support AI risk management efforts by others (Fact Sheet).
> A companion NIST AI RMF Playbook also has been published by NIST along with an AI RMF Roadmap, AI RMF Crosswalk, and various Perspectives.
> On March 30, 2023, NIST launched the Trustworthy and Responsible AI Resource Center, which will facilitate implementation of, and international alignment with, the AI RMF. Examples of how other organizations are building on and using the AI RMF can be found via the AIRC’s Use Case page.
> On July 26, 2024, NIST released NIST-AI-600-1, Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile. The profile can help organizations identify unique risks posed by generative AI and proposes actions for generative AI risk management that best aligns with their goals and priorities.
> To view public comments received on the previous drafts of the AI RMF and Requests for Information, see the AI RMF Development page.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 13. `genai.owasp.org-742d684f-e8cd56a3` (owasp-llm01.html, 209 words)

Section: (no heading)  
Concepts: prompt injection, model, prompt injection vulnerability, input, jailbreaking

> A Prompt Injection Vulnerability occurs when user prompts alter the LLM’s behavior or output in unintended ways. These inputs can affect the model even if they are imperceptible to humans, therefore prompt injections do not need to be human-visible/readable, as long as the content is parsed by the model.
> Prompt Injection vulnerabilities exist in how models process prompts, and how input may force the model to incorrectly pass prompt data to other parts of the model, potentially causing them to violate guidelines, generate harmful content, enable unauthorized access, or influence critical decisions. While techniques like Retrieval Augmented Generation (RAG) and fine-tuning aim to make LLM outputs more relevant and accurate, research shows that they do not fully mitigate prompt injection vulnerabilities.
> While prompt injection and jailbreaking are related concepts in LLM security, they are often used interchangeably. Prompt injection involves manipulating model responses through specific inputs to alter its behavior, which can include bypassing safety measures. Jailbreaking is a form of prompt injection where the attacker provides inputs that cause the model to disregard its safety protocols entirely. Developers can build safeguards into system prompts and input handling to help mitigate prompt injection attacks, but effective prevention of jailbreaking requires ongoing updates to the model’s training and safety mechanisms.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 14. `developers.google.com-0af9dc7e-3a1cb345` (google-seo-starter.html, 82 words)

Section: Search Engine Optimization (SEO) Starter Guide › How does Google Search work?  
Concepts: google, google search, site, web, fully automated search engine

> How does Google Search work?
> Google is a fully automated search engine that uses programs called crawlers to explore the web constantly, looking for pages to add to our index. You usually don't need to do anything except publish your site on the web. In fact, the vast majority of sites listed in our results are found and added automatically as we crawl the web. If you're hungry for more, we have documentation about how Google discovers, crawls, and serves web pages.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 15. `en.wikipedia.org-b43f8e16-4fb36358` (wikipedia-rag.html, 148 words)

Section: (no heading)  
Concepts: rag, llm, ai hallucination, ars technica, check retrieved content

> According to Ars Technica, "RAG is a way of improving LLM performance, in essence by blending the LLM process with a web search or other document look-up process to help LLMs stick to the facts." This method helps reduce AI hallucinations, which have caused chatbots to describe policies that don't exist, or recommend nonexistent legal cases to lawyers that are looking for citations to support their arguments.
> RAG also reduces the need to retrain LLMs with new data, saving on computational and financial costs. Beyond efficiency gains, RAG also allows LLMs to include sources in their responses, so users can verify the cited sources. This provides greater transparency, as users can cross-check retrieved content to ensure accuracy and relevance.
> The term retrieval-augmented generation (RAG) was introduced in a 2020 paper that described combining a parametric language model with a non-parametric external memory accessed through retrieval at inference time.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 16. `ftc.gov-5c252d1a-99b8bfd1` (ftc-advertising-hub.html, 162 words)

Section: (no heading)  
Concepts: consumer, advertising, certain protection, children online privacy protection act, fraudulent telemarketing call

> The internet connects marketers to customers across the country and around the world. If you advertise online, remember the rules and guidelines that protect consumers also help businesses by maintaining the credibility of the Internet as a marketing medium. In addition, truth-in-advertising standards apply if you sell computers, software, apps, or other products or services. The FTC also enforces the INFORM Consumers Act, which requires online marketplaces to verify the identity of high-volume third-party sellers on their platforms and make it easier for consumers to report suspicious conduct. (Question about kids' online privacy privacy? Read about the Children's Online Privacy Protection Act.)
> The FTC’s Telemarketing Sales Rule helps protect consumers from fraudulent telemarketing calls and gives them certain protections under the National Do Not Call Registry. Companies also need to be familiar with rules banning most forms of robocalling. If you or someone working on your behalf is telemarketing products or services, know the dos and don’ts before you plan your strategy.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 17. `ftc.gov-629fbc85-c701a532` (ftc-endorsement-faq.html, 214 words)

Section: WHAT ABOUT AFFILIATE OR NETWORK MARKETING? › Our company’s policy says that employees shouldn’t post positive reviews online about our products without clearly disclosing their relationship to the company. All of our employees agree to abide by…  
Concepts: employee, company policy, company website, review, social medium

> Our company’s policy says that employees shouldn’t post positive reviews online about our products without clearly disclosing their relationship to the company. All of our employees agree to abide by this policy when they’re hired. But we have several thousand people working here and we can’t monitor what they all do on their own computers and other devices when they aren’t at work. Are we liable if an employee posts a review of one of our products, either on our company website, on a third-party review site, or on social media, and doesn’t disclose that relationship?
> It wouldn’t be reasonable to expect you to monitor every social media posting by all of your employees. However, you should establish a formal program to remind employees periodically of your policy. Also, if you learn that employees have posted reviews on the company’s website or a social media site without adequately disclosing their relationship to the company, you should remind them of your company policy and ask them to remove those reviews or adequately disclose that they’re employees.
> If, however, you actively encouraged your employees to write reviews of your products, you would be responsible for monitoring them (both in terms of disclosing that they are employees and for problematic claims) despite any difficulty in doing so.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 18. `developers.google.com-8d7d5b41-e3710a11` (google-helpful-content.html, 142 words)

Section: Creating helpful, reliable, people-first content › Avoid creating search engine-first content  
Concepts: content, first content, search engine, lot, new content

> Avoid creating search engine-first content
> - Are you writing to a particular word count because you've heard or read that Google has a preferred word count? (No, we don't.)
> - Did you decide to enter some niche topic area without any real expertise, but instead mainly because you thought you'd get search traffic?
> - Does your content promise to answer a question that actually has no answer, such as suggesting there's a release date for a product, movie, or TV show when one isn't confirmed?
> - Are you changing the date of pages to make them seem fresh when the content has not substantially changed?
> - Are you adding a lot of new content or removing a lot of older content primarily because you believe it will help your search rankings overall by somehow making your site seem "fresh?" (No, it won't)

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 19. `lanternbooks.example-ee6351af-a6e39b6f` (synthetic-short-faq.html, 89 words)

Section: Gift Card FAQ  
Concepts: gift card, card, card number, gift card faq, balance

> Gift Card FAQ
> Do your gift cards expire?
> No. Our gift cards never expire, and any balance left after a purchase stays on the card for your next visit. You can check the balance at the till or by entering the card number on our help page.
> Can I use a gift card online?
> Yes. Enter the card number and the four-digit code at checkout. If the order costs more than the balance on the card, you can pay the difference with a bank card or another gift card.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**

### 20. `northwind-notes.example-8fee64f3-1e2762f5` (synthetic-subscriber-footer.html, 105 words)

Section: How to Write a Clear Email Opt-in Form › Confirm and follow through  
Concepts: form, double opt-in, long legal text, many people, mobile screen

> Confirm and follow through
> Send a short confirmation message straight away. It should repeat what the person signed up for, show when the next issue will arrive, and include a working unsubscribe link. A double opt-in, where the subscriber clicks a link to confirm, removes typing mistakes and keeps the list clean, although it costs a small share of sign-ups.
> Finally, test the form on a phone. Many people sign up from a mobile screen, where long legal text and tiny checkboxes are hard to use. A form that is easy to read on a small screen is usually easy to read everywhere else too.

- [ ] stands alone  - [ ] on topic  - [ ] no boilerplate  - [ ] readable  → **good / bad**
