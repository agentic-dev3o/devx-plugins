---
name: writing-landing-page-copy
description: Generates high-converting landing page copy through a structured interview and section-by-section writing process. Triggers when the user asks to write landing page copy, create a landing page, write marketing copy for a product, or generate conversion-optimized web copy.
---

# Landing Page Copywriting

Copy this checklist and track progress:

```
Workflow Progress:
- [ ] Phase 1: Discovery interview completed
- [ ] Phase 1: Brief confirmed by user
- [ ] Phase 2: Sections selected
- [ ] Phase 3: Copy generated for all selected sections
- [ ] Phase 4: Review pass completed
- [ ] Phase 4: User approved final copy
```

## Phase 1: Discovery Interview

Conduct a detailed interview before writing any copy. Use AskUserQuestion to gather information in 2-3 rounds.

### Round 1: Product & Market

Ask these questions together:

1. **Product**: What is the product/service? What does it do in one sentence?
2. **ICP (Ideal Customer Profile)**: Who is the primary buyer? (role, company size, industry)
3. **Core problem**: What painful problem does this solve? What happens if they do nothing?
4. **Main differentiator**: What makes this different from alternatives? Why would someone switch?

### Round 2: Value & Proof

5. **Top 3 benefits**: What are the three biggest outcomes customers get? (use numbers if possible)
6. **Process**: How does it work? Describe the user journey in 3 steps max
7. **Social proof**: What credibility signals exist? (customer logos, stats, testimonials, awards)
8. **Pricing model**: How is it priced? Any free tier or trial?

### Round 3: Strategy & Tone

9. **Primary CTA goal**: What action should visitors take? (sign up, book demo, start trial, buy)
10. **Urgency triggers**: Any legitimate scarcity? (limited seats, launch pricing, beta access)
11. **Tone adjustment**: Default is professional SaaS. Any preference? (bold, casual, technical, enterprise)

After gathering answers, summarize the brief back to the user for confirmation before writing.

## Phase 2: Section Selection

Present the available sections and let the user choose which to generate. Default to all.

| # | Section | Purpose |
|---|---------|---------|
| 1 | **Hero** | First impression - headline, subheadline, CTA |
| 2 | **Trust Bar** | Authority logos and social proof |
| 3 | **Loss Aversion** | Pain amplification before solution |
| 4 | **Benefits** | Outcome-focused value (rule of 3) |
| 5 | **Process** | How it works in 3 steps |
| 6 | **Features** | Technical proof and specs |
| 7 | **Pricing** | Plans, tiers, value framing |
| 8 | **Testimonials** | Social proof with specifics |
| 9 | **FAQ** | Objection handling |
| 10 | **Final CTA** | Closing push with urgency |

Use AskUserQuestion with multiSelect to let the user pick sections. Offer "All sections" as the first option.

## Phase 3: Write Copy

Generate each selected section following the detailed guidelines in [section-guide.md](references/section-guide.md).

For each section, apply the conversion psychology principles from [psychology.md](references/psychology.md).

### Output Format

ALWAYS use this exact structure for each section:

```markdown
---

## [Section Name]

> **Psychology**: [Which principle this section leverages]

### Headline
[Main headline text]

### Subheadline / Supporting
[Supporting text]

### Body
[Section body copy]

### CTA (if applicable)
[Button text] | [Supporting microcopy]

---
```

Apply standard copywriting best practices: clarity over cleverness, benefit-led headlines, specific numbers and timeframes, active voice, scannable formatting, ICP-appropriate language.

### Example

**Discovery brief (input)**:
Product: ShipFast, CI/CD for small teams. ICP: engineering leads at startups. Problem: slow, fragile pipelines. Differentiator: zero-config auto-detection. CTA: start free trial.

**Generated Hero section (output)**:

```markdown
---

## Hero

> **Psychology**: Self-Interest (WIIFM) + Social Proof

### Headline
Ship 3x faster without breaking production

### Subheadline / Supporting
The CI/CD platform built for teams that move fast. Set up in 5 minutes, not 5 sprints.

### CTA
Start building free | No credit card required

---
```

For more complete examples covering all sections, see [examples.md](references/examples.md).

## Phase 4: Review & Refine

After generating all sections, run this validation:

```
Review Checklist:
- [ ] Tone is consistent across all sections
- [ ] All CTAs point to the same primary goal
- [ ] FAQ addresses the top 3 objections from discovery
- [ ] No section duplicates messaging from another
- [ ] Numbers/metrics are specific, not vague
- [ ] Every headline passes the "so what?" test
```

If issues found, revise the affected sections and re-check. Use AskUserQuestion to ask which refinements the user wants.

## Additional Resources

- For detailed per-section writing guidelines, see [section-guide.md](references/section-guide.md)
- For conversion psychology principles, see [psychology.md](references/psychology.md)
- For real-world copy examples, see [examples.md](references/examples.md)
