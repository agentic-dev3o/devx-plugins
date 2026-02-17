---
name: building-landing-page
description: Generates a complete Astro 5 landing page with Tailwind CSS v4 from copywriting content. Triggers when the user asks to build a landing page, create the HTML/CSS for a landing page, generate an Astro site from copy, or implement a landing page design. Expects structured copywriting input matching the writing-landing-page-copy output format.
---

# Building Landing Page

Generates a production-ready Astro 5 + Tailwind CSS v4 landing page from structured copywriting content.

Copy this checklist and track progress:

```
Build Progress:
- [ ] Phase 1: Copywriting input validated
- [ ] Phase 2: Project scaffolded (astro config, package.json, tailwind)
- [ ] Phase 3: Base layout and global styles created
- [ ] Phase 4: Navbar and Footer components created
- [ ] Phase 5: Section components generated from copy
- [ ] Phase 6: Index page assembled
- [ ] Phase 7: Build verified
```

## Phase 1: Validate Input

Check that structured copywriting content exists. It should contain sections with this format:

```markdown
## [Section Name]
> **Psychology**: [principle]
### Headline
### Subheadline / Supporting
### Body
### CTA (if applicable)
```

If no copywriting exists yet, suggest running the `writing-landing-page-copy` skill first.

Confirm with the user:
1. **Project path**: Where to generate the project
2. **Brand customization**: Logo text/SVG, primary color (default: `#3b00ff`), font (default: Inter), site URL, organization name
3. **Sections to build**: Which sections from the copy to implement

## Phase 2: Scaffold Project

Generate the Astro 5 project. Follow the setup in [project-setup.md](references/project-setup.md) exactly.

Create these files:
- `package.json` - Astro 5, Tailwind v4, Node adapter, sitemap
- `astro.config.mjs` - SSR mode with Node adapter + Tailwind vite plugin
- `tsconfig.json` - Strict mode with `@/` path alias
- `src/styles/global.css` - Tailwind v4 imports + theme variables

Run `bun install` after scaffolding.

## Phase 3: Base Layout and Global Styles

Create `src/layouts/Base.astro` with:
- Full SEO meta tags (OG, Twitter, canonical)
- Google Fonts link (Inter by default)
- JSON-LD Organization schema (use site URL and organization name from Phase 1)
- Global CSS classes for effects (gradient-text, btn-glow, card-hover, hero-glow)
- `<slot />` for page content

Follow the design system defined in [design-system.md](references/design-system.md) for all color tokens, typography, spacing, and effect classes.

## Phase 4: Navbar and Footer

Create `src/components/Navbar.astro`:
- Sticky with backdrop-blur
- Desktop nav links (one per section) + mobile hamburger toggle
- Primary CTA button on the right
- Client-side JS for mobile menu toggle

Create `src/components/Footer.astro`:
- Logo + tagline
- Social/external links
- Copyright line

## Phase 5: Section Components

For each section in the copywriting input, generate a corresponding `.astro` component. Follow the component patterns in [components.md](references/components.md) for structure, props, and Tailwind classes.

Map copywriting sections to components:

| Copy Section | Component | Key Pattern |
|---|---|---|
| Hero | `Hero.astro` | Glow background, gradient text, primary CTA button |
| Trust Bar | `TrustBar.astro` | Monochrome logo row, "Trusted by X" context |
| Loss Aversion | `PainPoints.astro` | 3 pain cards with icons, dark bg, empathetic tone |
| Benefits | `Benefits.astro` | Rule-of-3 cards with icons, hover lift |
| Process | `Process.astro` | 3 numbered steps, light bg, time estimates |
| Features | `Features.astro` | 6-8 feature grid, icon + name + description |
| Pricing | `Pricing.astro` | 2-3 tier cards, highlighted recommended, feature checklist |
| Testimonials | `Testimonials.astro` | Quote cards with attribution, avatar placeholder |
| FAQ | `FAQ.astro` | Native `<details>` accordion, chevron rotation |
| Final CTA | `FinalCTA.astro` | Repeat hero CTA, glow background, secondary link |

Each component:
- Accepts props typed with a TypeScript interface
- Uses content from the copywriting directly as prop defaults
- Follows the alternating dark/light section pattern
- Includes responsive breakpoints (mobile-first, `md:` for desktop)

## Phase 6: Assemble Index Page

Create `src/pages/index.astro` that imports and composes all section components in order:

```astro
---
import Base from "@/layouts/Base.astro"
import Navbar from "@/components/Navbar.astro"
import Hero from "@/components/Hero.astro"
// ... remaining sections
import Footer from "@/components/Footer.astro"
---

<Base title="...">
  <Navbar />
  <main>
    <Hero />
    <!-- sections in copywriting order -->
  </main>
  <Footer />
</Base>
```

Pass copywriting content as props or inline it directly in the component files.

## Phase 7: Verify Build

Run:
```bash
bun run build
```

Fix any TypeScript or Tailwind errors. Verify the output renders correctly.

### Example

**Copywriting Hero input**:
```markdown
## Hero
> **Psychology**: Self-Interest (WIIFM) + Social Proof
### Headline
Ship 3x faster without breaking production
### Subheadline / Supporting
The CI/CD platform built for teams that move fast. Set up in 5 minutes, not 5 sprints.
### CTA
Start building free | No credit card required
```

**Generated Hero.astro output**:
```astro
---
interface Props {
  title?: string
  highlightedText?: string
  subtitle?: string
  ctaText?: string
  ctaHref?: string
  ctaMicrocopy?: string
}

const {
  title = "Ship 3x faster",
  highlightedText = "without breaking production.",
  subtitle = "The CI/CD platform built for teams that move fast.\nSet up in 5 minutes, not 5 sprints.",
  ctaText = "Start building free",
  ctaHref = "#pricing",
  ctaMicrocopy = "No credit card required",
} = Astro.props
---

<section class="relative overflow-hidden pt-32 pb-24">
  <div class="hero-glow absolute top-0 left-1/4"></div>
  <div class="hero-glow absolute top-0 right-1/4"></div>
  <div class="max-w-4xl mx-auto px-6 text-center relative z-10">
    <h1 class="text-5xl md:text-6xl lg:text-7xl font-extrabold tracking-tight mb-6">
      {title}<br />
      <span class="gradient-text">{highlightedText}</span>
    </h1>
    <p class="text-xl text-slate-300 mb-10 max-w-2xl mx-auto whitespace-pre-line">
      {subtitle}
    </p>
    <a href={ctaHref}
       class="group inline-flex items-center gap-2 bg-linear-to-r from-primary to-primary-light hover:from-primary-dark hover:to-primary text-white text-lg px-8 py-4 rounded-full btn-glow font-semibold transition-all">
      {ctaText}
      <svg class="w-5 h-5 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
      </svg>
    </a>
    <p class="text-sm text-slate-400 mt-4">{ctaMicrocopy}</p>
  </div>
</section>
```

