# Component Templates

Astro component patterns for each landing page section. Each component is self-contained with typed props and responsive Tailwind styling.

## Contents
- Base.astro (layout)
- Navbar.astro
- Hero.astro
- TrustBar.astro
- PainPoints.astro (Loss Aversion)
- Benefits.astro
- Process.astro
- Features.astro
- Pricing.astro
- Testimonials.astro
- FAQ.astro
- FinalCTA.astro
- Footer.astro

---

## Base.astro

Layout wrapper. All pages use this.

**Props:**
```typescript
interface Props {
  title: string
  description?: string
  image?: string
  canonicalUrl?: string
  organizationName?: string
  siteUrl?: string
}
```

**Structure:**
```astro
<html lang="en">
  <head>
    <!-- charset, viewport, title, description -->
    <!-- OG meta: og:title, og:description, og:image, og:type -->
    <!-- Twitter meta: twitter:card, twitter:title, twitter:description, twitter:image -->
    <!-- Google Fonts: Inter (400,500,600,700,800) -->
    <!-- canonical link if provided -->
  </head>
  <body class="bg-dark text-white font-display antialiased">
    <slot />
    <!-- global style block with effect classes (see design-system.md) -->
  </body>
</html>
```

Include all effect classes (`.gradient-text`, `.hero-glow`, `.card-hover`, `.btn-glow`) in a `<style is:global>` block.

---

## Navbar.astro

Sticky navigation with mobile hamburger.

**Props:** None. Hardcode nav links to section anchors.

**Structure:**
```
<nav> sticky top-0 z-50 bg-dark/90 backdrop-blur-xl border-b border-dark-border/50
  <div> max-w-6xl mx-auto px-6 h-16 flex items-center justify-between
    LEFT:  Logo text or SVG (link to /)
    CENTER (desktop): hidden md:flex gap-8 — anchor links to #sections
    RIGHT: Primary CTA button (hidden on mobile)
    MOBILE: Hamburger button (md:hidden)
  </div>
  MOBILE MENU: md:hidden hidden — vertical list of links + CTA
</nav>
```

**Client JS:** Toggle mobile menu visibility and hamburger/close icon swap.

```html
<script>
  const btn = document.getElementById("menu-btn")
  const menu = document.getElementById("mobile-menu")
  const iconOpen = document.getElementById("icon-open")
  const iconClose = document.getElementById("icon-close")

  btn?.addEventListener("click", () => {
    const expanded = btn.getAttribute("aria-expanded") === "true"
    btn.setAttribute("aria-expanded", String(!expanded))
    menu?.classList.toggle("hidden")
    iconOpen?.classList.toggle("hidden")
    iconClose?.classList.toggle("hidden")
  })

  menu?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      menu.classList.add("hidden")
      btn?.setAttribute("aria-expanded", "false")
      iconOpen?.classList.remove("hidden")
      iconClose?.classList.add("hidden")
    })
  })
</script>
```

**Nav links:** One per visible section (Benefits, Features, Pricing, FAQ).

---

## Hero.astro

**Background:** Dark with two `hero-glow` elements positioned top-left and top-right.

**Props:**
```typescript
interface Props {
  title?: string
  highlightedText?: string
  subtitle?: string
  ctaText?: string
  ctaHref?: string
  ctaMicrocopy?: string
}
```

**Layout:** `pt-32 pb-24`, `max-w-4xl mx-auto px-6 text-center relative z-10`

**Elements:**
- `<h1>` with responsive sizing: `text-5xl md:text-6xl lg:text-7xl font-extrabold tracking-tight`
- Highlighted text in `<span class="gradient-text">`
- Subtitle: `text-xl text-slate-300 max-w-2xl mx-auto whitespace-pre-line`
- Primary CTA: gradient button with `btn-glow` and arrow icon
- Microcopy: `text-sm text-slate-400 mt-4`

---

## TrustBar.astro

Thin section immediately after hero. Dark background.

**Props:**
```typescript
interface Props {
  label?: string       // "Trusted by 500+ companies"
  logos?: string[]     // Company names (rendered as text if no SVGs)
}
```

**Layout:** `py-12`, `max-w-5xl mx-auto px-6 text-center`

**Elements:**
- Label: `text-sm text-slate-400 uppercase tracking-wider font-medium mb-8`
- Logo row: `flex flex-wrap items-center justify-center gap-8 md:gap-12`
- Each logo: `text-slate-500 text-lg font-semibold opacity-60` (placeholder text style, replace with SVGs when available)

---

## PainPoints.astro

Maps to the Loss Aversion copy section. Dark background.

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  painPoints?: Array<{ headline: string; description: string }>
  closingMessage?: string
}
```

**Layout:** `py-24`, `max-w-4xl mx-auto px-6`

**Elements:**
- Label: `text-sm text-primary-light uppercase tracking-wider font-semibold`
- Title: `text-3xl md:text-4xl font-bold text-white mt-3 mb-12`
- Pain cards: `grid sm:grid-cols-2 gap-4` if 4 items, or `space-y-6` if 3
- Each card: dark card pattern with SVG icon (warning/alert style) in `text-primary-light`
  - Headline: `font-semibold text-white`
  - Description: `text-slate-300 text-sm`
- Closing: `gradient-text font-semibold` after a `border-t border-dark-border pt-8`

---

## Benefits.astro

Light background (`bg-gray-50`).

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  benefits?: Array<{ icon?: string; headline: string; description: string }>
}
```

**Layout:** `py-24 bg-gray-50`, `max-w-5xl mx-auto px-6`

**Elements:**
- Section label + title: dark text (`text-gray-900`)
- Cards: `grid sm:grid-cols-2 lg:grid-cols-3 gap-6` (use 2 cols if 2 benefits, 3 if 3)
- Each card: light card pattern
  - Icon container: `w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center`
  - Headline: `text-lg font-semibold text-gray-900`
  - Description: `text-gray-600`

---

## Process.astro

Dark background with subtle radial glow.

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  steps?: Array<{ number: number; headline: string; description: string; time?: string }>
}
```

**Layout:** `py-24 relative`, `max-w-5xl mx-auto px-6`

**Elements:**
- Centered radial glow: `absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-radial from-primary/5 to-transparent rounded-full blur-3xl`
- Steps: `grid md:grid-cols-3 gap-8`
- Each step:
  - Number badge: `w-12 h-12 bg-linear-to-br from-primary to-primary-light rounded-full flex items-center justify-center text-white font-bold text-lg`
  - Headline: `text-lg font-semibold text-white mt-4`
  - Description: `text-slate-300 mt-2`
  - Time estimate (if provided): `text-sm text-primary-light mt-1`

---

## Features.astro

Light background (`bg-gray-50`).

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  features?: Array<{ name: string; description: string }>
}
```

**Layout:** `py-24 bg-gray-50`, `max-w-5xl mx-auto px-6`

**Elements:**
- Grid: `grid sm:grid-cols-2 lg:grid-cols-3 gap-6`
- Each feature: light card pattern
  - Icon: generic feature icon in `text-primary`
  - Name: `font-semibold text-gray-900`
  - Description: `text-gray-600 text-sm`

---

## Pricing.astro

Dark background with radial glow. Highlight the recommended tier.

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  subtitle?: string
  tiers?: Array<{
    name: string
    price: string
    frequency?: string
    description: string
    features: Array<{ text: string; included: boolean }>
    ctaText: string
    ctaHref?: string
    highlighted?: boolean
  }>
}
```

**Layout:** `py-24 relative`, `max-w-6xl mx-auto px-6`

**Elements:**
- Grid: `grid md:grid-cols-3 gap-6 items-start` (adjust cols to tier count)
- Regular tier: dark card pattern
- Highlighted tier: dark card with glow pseudo-element + "Most popular" badge
  - Badge: `absolute -top-4 left-1/2 -translate-x-1/2 bg-linear-to-r from-primary to-primary-light text-white text-xs font-semibold px-4 py-1.5 rounded-full`
- Price: `text-5xl font-bold text-white`
- Frequency: `text-slate-400`
- Feature list: `space-y-3`
  - Included: emerald checkmark + `text-slate-300`
  - Excluded: slate X + `text-slate-500 line-through`
- CTA: gradient button for highlighted, border button for others

---

## Testimonials.astro

Light background (`bg-gray-50`).

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  testimonials?: Array<{
    quote: string
    name: string
    jobTitle: string
    company?: string
    metric?: string
  }>
}
```

**Layout:** `py-24 bg-gray-50`, `max-w-5xl mx-auto px-6`

**Elements:**
- Grid: `grid md:grid-cols-3 gap-6` (adjust to testimonial count, use 2-cols if 2)
- Each card: light card pattern
  - Quote mark: `text-4xl text-primary/30 font-serif leading-none mb-2` — `"`
  - Quote text: `text-gray-700 italic`
  - Metric (if present): `text-primary font-bold text-lg mt-3`
  - Divider: `border-t border-gray-200 mt-4 pt-4`
  - Avatar placeholder: `w-10 h-10 rounded-full bg-linear-to-br from-primary to-primary-light flex items-center justify-center text-white font-semibold text-sm` — initials
  - Name: `font-semibold text-gray-900`
  - Job title + company: `text-sm text-gray-500`

---

## FAQ.astro

Light background. Uses native HTML `<details>` for zero-JS accordion.

**Props:**
```typescript
interface Props {
  label?: string
  title?: string
  questions?: Array<{ question: string; answer: string }>
}
```

**Layout:** `py-24 bg-gray-50`, `max-w-3xl mx-auto px-6`

**Elements:**
- Stack: `space-y-4`
- Each item:
```html
<details class="group bg-white rounded-2xl border border-gray-200 overflow-hidden">
  <summary class="flex items-center justify-between p-6 cursor-pointer">
    <span class="font-semibold text-gray-900 pr-4">{question}</span>
    <svg class="w-5 h-5 text-gray-400 shrink-0 group-open:rotate-180 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
    </svg>
  </summary>
  <div class="px-6 pb-6 text-gray-600">{answer}</div>
</details>
```

---

## FinalCTA.astro

Dark background with radial glow at top.

**Props:**
```typescript
interface Props {
  headline?: string
  subtitle?: string
  ctaText?: string
  ctaHref?: string
  ctaMicrocopy?: string
  secondaryText?: string
  secondaryHref?: string
}
```

**Layout:** `py-24 relative`, `max-w-3xl mx-auto px-6 text-center relative z-10`

**Elements:**
- Radial glow: `absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-radial from-primary/10 to-transparent rounded-full blur-3xl`
- Headline: `text-3xl md:text-4xl font-bold text-white mb-4`
- Subtitle: `text-lg text-slate-300 mb-8`
- Primary CTA: same gradient button as Hero (with `btn-glow` and arrow icon)
- Microcopy: `text-sm text-slate-400 mt-4`
- Secondary link (optional): `text-slate-300 hover:text-white underline transition-colors`

---

## Footer.astro

**Props:** None. Hardcode brand info and links.

**Structure:**
```
<footer> py-16 border-t border-dark-border
  <div> max-w-6xl mx-auto px-6
    ROW: flex flex-col md:flex-row items-center justify-between gap-8
      LEFT: Logo text + tagline (text-slate-400)
      RIGHT: flex gap-6 — external links (text-slate-300 hover:text-white)
    COPYRIGHT: text-center text-sm text-slate-500 mt-8 pt-8 border-t border-dark-border
  </div>
</footer>
```
