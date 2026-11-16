# AI-10 chunk quality report (2026-10-25)

**Automatic gates: PASS.** **Human review: PASS** — 20 of 20 sampled chunks good (pass at 18), reviewed by Ziad Abdullah on 2026-10-25. **AI-10 is done.**

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

The sample is spread evenly over the 11 pages that have chunks: each page gets one chunk before any page gets a second (seed 8).

For each chunk, tick every box that holds, then mark it good only if all four do.
- **Stands alone:** makes sense without the chunks around it.
- **On topic:** about one subject, the one its section names.
- **No boilerplate:** no menus, cookie text, footers or ads.
- **Readable:** no broken sentences, glued words or stray markup.

Reviewer: Ziad Abdullah  Date: 2026-10-25  Good chunks: 20 / 20 (pass at 18)

### 1. `shipwright.example-a339dbca-ef4df88e` (synthetic-div-soup.html, 180 words)

Section: (no heading)  
Concepts: change, user, added csv export service, breaking change, first line

> Most release notes are written for the team that shipped the change, not for the people who have to live with it. They list ticket numbers, internal code names and refactors that no user will ever notice, while the one change that breaks a workflow is buried in the middle.
> Start with the changes that require action. If a setting moved, an old behaviour was removed or an integration needs to be reconnected, say so in the first lines and explain what to do. Users forgive a breaking change much more easily when the notes tell them exactly how to adapt.
> Next, describe new features in terms of what users can now do, not what the team built. A sentence such as "you can now export reports as spreadsheets from the dashboard" is clearer than "added CSV export service". Link to a short guide when a feature needs more than two sentences.
> Group small fixes into a single list at the end and keep each item to one line. People scan this part, so plain words matter more than completeness.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 2. `ftc.gov-194ba0c8-1e574e8b` (ftc-can-spam.html, 126 words)

Section: (no heading)  
Concepts: recipient, message, certain type, clear and conspicuous explanation, creative use

> - Tell recipients how to opt out of receiving future marketing email from you. Your message must include a clear and conspicuous explanation of how the recipient can opt out of getting marketing email from you in the future. Craft the notice in a way that’s easy for an ordinary person to recognize, read, and understand. Creative use of type size, color, and location can improve clarity. Give a return email address or another easy Internet-based way to allow people to communicate their choice to you. You may create a menu to allow a recipient to opt out of certain types of messages, but you must include the option to stop all marketing messages from you. Make sure your spam filter doesn’t block these opt-out requests.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 3. `northwind-notes.example-8fee64f3-1e2762f5` (synthetic-subscriber-footer.html, 105 words)

Section: How to Write a Clear Email Opt-in Form › Confirm and follow through  
Concepts: form, double opt-in, long legal text, many people, mobile screen

> Confirm and follow through
> Send a short confirmation message straight away. It should repeat what the person signed up for, show when the next issue will arrive, and include a working unsubscribe link. A double opt-in, where the subscriber clicks a link to confirm, removes typing mistakes and keeps the list clean, although it costs a small share of sign-ups.
> Finally, test the form on a phone. Many people sign up from a mobile screen, where long legal text and tiny checkboxes are hard to use. A form that is easy to read on a small screen is usually easy to read everywhere else too.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 4. `en.wikipedia.org-b43f8e16-92959619` (wikipedia-rag.html, 70 words)

Section: RAG and LLM limitations  
Concepts: prompt stuffing, rag and llm limitation, additional relevant context, key information, llm

> RAG and LLM limitations
> LLMs with RAG are programmed to prioritize new information. This technique has been called "prompt stuffing." Without prompt stuffing, the LLM's input is generated by a user; with prompt stuffing, additional relevant context is added to this input to guide the model's response. This approach provides the LLM with key information early in the prompt, encouraging it to prioritize the supplied data over pre-existing training knowledge.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 5. `developers.google.com-0af9dc7e-a43e7190` (google-seo-starter.html, 136 words)

Section: Search Engine Optimization (SEO) Starter Guide › Help Google find your content › Check if Google can see your page the same way a user does  
Concepts: google, page, search result, average user, crawler location

> Check if Google can see your page the same way a user does
> When Google crawls a page, it should ideally see the page the same way an average user does. For this, Google needs to be able to access the same resources as the user's browser. If your site is hiding important components that make up your website (like CSS and JavaScript), Google might not be able to understand your pages, which means they might not show up in search results or rank well for the terms you're targeting.
> If your pages have different information depending on the user's physical location, make sure you're satisfied with the information that Google sees from its crawler's location, which is generally the US.
> To check how Google sees your page, use the URL Inspection Tool in Search Console.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 6. `ftc.gov-629fbc85-2051a490` (ftc-endorsement-faq.html, 153 words)

Section: HOW SHOULD I DISCLOSE THAT I WAS GIVEN SOMETHING FOR MY ENDORSEMENT? › What about having a disclosure in the description of an Instagram post? Is that good enough?  
Concepts: instagram post, description, disclosure, endorsement, video

> What about having a disclosure in the description of an Instagram post? Is that good enough?
> When people view Instagram streams, longer descriptions are truncated, with only the first two or three lines displayed. To see the rest, you have to click “more.” If an Instagram post makes an endorsement in the beginning of the description, any required disclosure should be presented without having to click “more.”
> If the picture on an Instagram post conveys an endorsement without the viewer having to read the accompanying description and a significant minority of viewers don’t read the description, a disclosure in the description could be inadequate. You might need a disclosure superimposed over the picture. Also, if an Instagram post makes an endorsement in a video, there should be a disclosure in the video, preferably both visually and audibly. (See the discussion in “So, can I just superimpose a larger text disclosure over my video?”)

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 7. `ftc.gov-5c252d1a-99b8bfd1` (ftc-advertising-hub.html, 162 words)

Section: (no heading)  
Concepts: consumer, advertising, certain protection, children online privacy protection act, fraudulent telemarketing call

> The internet connects marketers to customers across the country and around the world. If you advertise online, remember the rules and guidelines that protect consumers also help businesses by maintaining the credibility of the Internet as a marketing medium. In addition, truth-in-advertising standards apply if you sell computers, software, apps, or other products or services. The FTC also enforces the INFORM Consumers Act, which requires online marketplaces to verify the identity of high-volume third-party sellers on their platforms and make it easier for consumers to report suspicious conduct. (Question about kids' online privacy privacy? Read about the Children's Online Privacy Protection Act.)
> The FTC’s Telemarketing Sales Rule helps protect consumers from fraudulent telemarketing calls and gives them certain protections under the National Do Not Call Registry. Companies also need to be familiar with rules banning most forms of robocalling. If you or someone working on your behalf is telemarketing products or services, know the dos and don’ts before you plan your strategy.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 8. `developers.google.com-8d7d5b41-b7547b59` (google-helpful-content.html, 117 words)

Section: Creating helpful, reliable, people-first content › Ask "Who, How, and Why" about your content › Why (was the content created)  
Concepts: content, e-e-a-t, ai-generation, core ranking system, first place

> Why (was the content created)
> "Why" is perhaps the most important question to answer about your content. Why is it being created in the first place?
> The "why" should be that you're creating content primarily to help people, content that is useful to visitors if they come to your site directly. If you're doing this, you're aligning with E-E-A-T generally and what our core ranking systems seek to reward.
> If the "why" is that you're primarily making content to attract search engine visits, that's not aligned with what our systems seek to reward. If you use automation, including AI-generation, to produce content for the primary purpose of manipulating search rankings, that's a violation of our spam policies.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 9. `genai.owasp.org-430c5292-4d5c9bd8` (owasp-llm01.html, 116 words)

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

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

Reviewer note: a stray backslash at the end of the sub-heading comes from the source page; minor, still good.

### 10. `lanternbooks.example-ee6351af-a6e39b6f` (synthetic-short-faq.html, 89 words)

Section: Gift Card FAQ  
Concepts: gift card, card, card number, gift card faq, balance

> Gift Card FAQ
> Do your gift cards expire?
> No. Our gift cards never expire, and any balance left after a purchase stays on the card for your next visit. You can check the balance at the till or by entering the card number on our help page.
> Can I use a gift card online?
> Yes. Enter the card number and the four-digit code at checkout. If the order costs more than the balance on the card, you can pay the difference with a bank card or another gift card.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 11. `nist.gov-54dbc154-25768e49` (nist-ai-rmf.html, 126 words)

Section: (no heading)  
Concepts: ai rmf, ai product, ai program, ai rmf profile, ai-enabled capability

> On April 7, 2026, NIST released a concept note for an AI RMF Profile on Trustworthy AI in Critical Infrastructure. The profile will guide critical infrastructure operators towards specific risk management practices to consider when engaging AI-enabled capabilities.
> The AI RMF 1.0 is being revised as part of the White House AI Action Plan.
> Led by the Information Technology Laboratory (ITL) AI Program, and in collaboration with the private and public sectors, NIST has developed a framework to better manage risks to individuals, organizations, and society associated with artificial intelligence (AI). The NIST AI Risk Management Framework (AI RMF) is intended for voluntary use and to improve the ability to incorporate trustworthiness considerations into the design, development, use, and evaluation of AI products, services, and systems.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 12. `shipwright.example-a339dbca-5ae2cfb7` (synthetic-div-soup.html, 83 words)

Section: (no heading)  
Concepts: changelog page, consistent date, group small fix, internal clean-up work, single list

> Group small fixes into a single list at the end and keep each item to one line. People scan this part, so plain words matter more than completeness. Internal clean-up work can be left out entirely unless it changes performance in a way users will feel.
> Finally, publish the notes where users already look: inside the product, in the changelog page and in the email that announces the release. Consistent dates and version numbers across those places help support teams answer questions quickly.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 13. `ftc.gov-194ba0c8-42325e50` (ftc-can-spam.html, 158 words)

Section: Q. What if the message combines commercial content and transactional or relationship content?  
Concepts: message, commercial content, message a, transactional or relationship content, accounts receivable department

> Q. What if the message combines commercial content and transactional or relationship content?
> MESSAGE A TO: Jane Smith FR: XYZ Distributing RE: Your Account Statement We shipped your order of 25,000 deluxe widgets to your Springfield warehouse on June 1st. We hope you received them in good working order. Please call our Customer Service Office at (877) 555-7726 if any widgets were damaged in transit. Per our contract, we must receive your payment of $1,000 by June 30th. If not, we will impose a 10% surcharge for late payment. If you have any questions, please contact our Accounts Receivable Department. Visit our website for our exciting new line of mini-widgets!
> MESSAGE A is most likely a transactional or relationship message subject only to CAN-SPAM’s requirement of truthful routing information. One important factor is that information about the customer’s account is at the beginning of the message and the brief commercial portion of the message is at the end.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 14. `northwind-notes.example-8fee64f3-32ff4174` (synthetic-subscriber-footer.html, 59 words)

Section: How to Write a Clear Email Opt-in Form › Ask only for what you need  
Concepts: email address, extra field, form, most newsletter, other detail

> Ask only for what you need
> Every extra field lowers the number of people who finish the form. For most newsletters an email address is enough at the start. If you want a first name for personalisation, make it optional and explain why you ask. Collect other details later, once the subscriber trusts you and can see the benefit.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 15. `en.wikipedia.org-b43f8e16-74f255e4` (wikipedia-rag.html, 166 words)

Section: (no heading)  
Concepts: llm, rag, retrieval-augmented generation, ars technica, authoritative source

> Retrieval-augmented generation (RAG) is a technique that enables large language models (LLMs) to retrieve and incorporate new information from external data sources. With RAG, LLMs first refer to a specified set of documents, then respond to user queries. These documents supplement information from the LLM's pre-existing training data. This allows LLMs to use domain-specific and/or updated information that is not available in the training data. For example, this enables LLM-based chatbots to access internal company data or generate responses based on authoritative sources. The technique was first proposed in 2020 and has since become a widely adopted approach in modern AI systems.
> RAG improves LLMs by incorporating information retrieval before generating responses. Unlike LLMs that rely on static training data, RAG pulls relevant text from databases, uploaded documents, or web sources. According to Ars Technica, "RAG is a way of improving LLM performance, in essence by blending the LLM process with a web search or other document look-up process to help LLMs stick to the facts."

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 16. `developers.google.com-0af9dc7e-0e5091d5` (google-seo-starter.html, 165 words)

Section: Search Engine Optimization (SEO) Starter Guide  
Concepts: search engine optimization, site, content, search engine, seo

> Search Engine Optimization (SEO) Starter Guide
> When you built your website, you likely created it with your users in mind, trying to make it easy for them to find and explore your content. One of those users is a search engine, which helps people discover your content. SEO—short for search engine optimization—is about helping search engines understand your content, and helping users find your site and make a decision about whether they should visit your site through a search engine.
> The Search Essentials outline the most important elements of what makes your website eligible to appear on Google Search. While there's no guarantee that any particular site will be added to Google's index, sites that follow the Search Essentials are more likely to show up in Google's search results. SEO is about taking the next step and working on improving your site's presence in Search. This guide will walk you through some of the most common and effective improvements you can do on your site.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 17. `ftc.gov-629fbc85-140e54b4` (ftc-endorsement-faq.html, 62 words)

Section: HOW SHOULD I DISCLOSE THAT I WAS GIVEN SOMETHING FOR MY ENDORSEMENT?  
Concepts: brand, connection, my endorsement, social media post, sufficient disclosure

> HOW SHOULD I DISCLOSE THAT I WAS GIVEN SOMETHING FOR MY ENDORSEMENT?
> Is tagging a brand in a social media post a sufficient disclosure that I have a connection to a brand?
> No. Tagging a brand is an endorsement, but it’s not a disclosure that you have a connection to a brand. You could just be tagging it because you like it.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 18. `ftc.gov-5c252d1a-5ce3c6b9` (ftc-advertising-hub.html, 156 words)

Section: (no heading)  
Concepts: additional rule, advertising, advertising (endorsement guides, child, children online privacy protection act

> Under the law, claims in advertisements must be truthful, cannot be deceptive or unfair, and must be evidence-based. For some specialized products or services, additional rules may apply.
> If you advertise directly to children or market kid-related products to their parents, it’s important to comply with truth-in-advertising standards. (Questions about kids’ privacy? Check out the FTC's resources about COPPA, the Children’s Online Privacy Protection Act. The FTC also has a special page about food advertising to children and adolescents.)
> If you use consumer reviews or endorsements in your marketing, are you both meeting the standards of the FTC Act and complying with the specific prohibitions of the Rule on the Use of Consumer Reviews and Testimonials? What about the FTC's Guides Concerning Use of Endorsements and Testimonials in Advertising (Endorsement Guides), revised in 2023? Get plain language guidance from the FTC related to reviews, social media influencers, and for complying with the Consumer Review Fairness Act.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 19. `developers.google.com-8d7d5b41-19ceeaab` (google-helpful-content.html, 154 words)

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

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**

### 20. `genai.owasp.org-430c5292-ecbb0b0e` (owasp-llm01.html, 166 words)

Section: Prevention and Mitigation Strategies  
Concepts: prevention and mitigation strategies, prompt injection, clear output format, constrain model behavior, context relevance

> Prevention and Mitigation Strategies
> Prompt injection vulnerabilities are possible due to the nature of generative AI. Given the stochastic influence at the heart of the way models work, it is unclear if there are fool-proof methods of prevention for prompt injection. However, the following measures can mitigate the impact of prompt injections:
> 1. Constrain model behavior
> Provide specific instructions about the model’s role, capabilities, and limitations within the system prompt. Enforce strict context adherence, limit responses to specific tasks or topics, and instruct the model to ignore attempts to modify core instructions.
> 2. Define and validate expected output formats
> Specify clear output formats, request detailed reasoning and source citations, and use deterministic code to validate adherence to these formats.
> 3. Implement input and output filtering
> Define sensitive categories and construct rules for identifying and handling such content. Apply semantic filters and use string-checking to scan for non-allowed content. Evaluate responses using the RAG Triad: Assess context relevance, groundedness, and question/answer relevance to identify potentially malicious outputs.

- [x] stands alone  - [x] on topic  - [x] no boilerplate  - [x] readable  → **good**
