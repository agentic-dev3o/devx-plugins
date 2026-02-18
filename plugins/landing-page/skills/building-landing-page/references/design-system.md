# Design System

Design tokens and utility classes for the landing page. Based on a dark-theme SaaS aesthetic with vibrant purple accent.

## Contents
- Color Tokens (Tailwind v4 @theme)
- Typography
- Spacing and Layout
- Effect Classes (gradient-text, btn-glow, card-hover, hero-glow)
- Card Patterns
- Button Patterns
- Icon Patterns
- Responsive Breakpoints
- Section Alternation

---

## Color Tokens

Color tokens are defined in `src/styles/global.css` via Tailwind v4 `@theme` — see [project-setup.md](project-setup.md) for the canonical file content. The user may customize `--color-primary` during Phase 1; derive `-light` (lighter 15%) and `-dark` (darker 15%) variants accordingly.

**Available tokens:** `primary`, `primary-light`, `primary-dark`, `dark`, `dark-lighter`, `dark-border`.

**Semantic usage:**
- `bg-dark` / `bg-dark-lighter` - Dark section backgrounds and cards
- `bg-gray-50` - Light section backgrounds
- `text-primary` / `text-primary-light` - Accent text, icons, links
- `text-white` - Headings on dark backgrounds
- `text-slate-300` / `text-slate-400` - Body text on dark backgrounds
- `text-gray-900` / `text-gray-600` - Text on light backgrounds
- `border-dark-border` - Card and divider borders on dark backgrounds
- `bg-emerald-500/20` + `text-emerald-400` - Success/checkmark indicators

---

## Typography

**Font**: Inter from Google Fonts (weights: 400, 500, 600, 700, 800).

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
```

**Scale:**

| Element | Classes |
|---|---|
| Hero H1 | `text-5xl md:text-6xl lg:text-7xl font-extrabold tracking-tight` |
| Section H2 | `text-3xl md:text-4xl font-bold` |
| Section H3 | `text-xl md:text-2xl font-bold` |
| Card title | `text-lg font-semibold` or `font-bold` |
| Body | `text-base` (default) or `text-lg` for emphasis |
| Small text | `text-sm text-slate-400` |
| Labels/badges | `text-xs font-semibold uppercase tracking-wider` |

---

## Spacing and Layout

**Section padding**: `py-24` (consistent vertical rhythm).

**Container widths** (centered with `mx-auto px-6`):

| Context | Class | Use |
|---|---|---|
| Wide sections | `max-w-6xl` | Pricing grids, feature grids |
| Standard sections | `max-w-5xl` | Benefits, process, features |
| Narrow sections | `max-w-4xl` | Hero, pain points, enterprise |
| Text-focused | `max-w-3xl` | FAQ, final CTA |

**Grid gaps**: `gap-4` (tight), `gap-6` (standard), `gap-8` (loose).

---

## Effect Classes

Define these in `Base.astro` inside `<style is:global>`:

```css
.gradient-text {
  background: linear-gradient(135deg, var(--color-primary), var(--color-primary-light), #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-glow {
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, var(--color-primary) 0%, transparent 70%);
  opacity: 0.15;
  filter: blur(100px);
  pointer-events: none;
}

.card-hover {
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s;
}
.card-hover:hover {
  transform: translateY(-4px);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
}

.btn-glow {
  box-shadow: 0 0 20px color-mix(in srgb, var(--color-primary) 40%, transparent),
              0 0 60px color-mix(in srgb, var(--color-primary) 20%, transparent);
}
```

---

## Card Patterns

**Dark card** (on dark sections):
```
bg-dark-lighter/50 backdrop-blur rounded-2xl border border-dark-border p-6 md:p-8
```

**Light card** (on light sections):
```
bg-white rounded-2xl border border-gray-200 shadow-sm p-6 hover:shadow-md hover:-translate-y-1 transition-all duration-200
```

**Featured card** (pricing highlight):
```
relative group
```
With glow pseudo-element:
```
absolute -inset-1 bg-linear-to-r from-primary to-primary-light rounded-3xl blur opacity-40 group-hover:opacity-60 transition
```

---

## Button Patterns

**Primary CTA** (gradient with glow):
```
group inline-flex items-center gap-2 bg-linear-to-r from-primary to-primary-light hover:from-primary-dark hover:to-primary text-white px-8 py-4 rounded-full btn-glow font-semibold transition-all
```

**Secondary CTA** (dark border):
```
inline-flex items-center gap-2 border border-dark-border text-white px-6 py-3 rounded-full hover:bg-dark-lighter transition-colors font-medium
```

**Light background CTA**:
```
inline-flex items-center gap-2 bg-linear-to-r from-primary to-primary-light text-white px-6 py-3 rounded-xl hover:from-primary-dark hover:to-primary transition-all font-semibold
```

**Arrow icon** (append to CTA buttons):
```html
<svg class="w-5 h-5 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
</svg>
```

---

## Icon Patterns

**Section icons** (in cards): Inline SVG, `w-6 h-6`, `stroke="currentColor"`, `text-primary-light`.

**Icon container** (badge style):
```
w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center shrink-0
```
Or gradient version:
```
w-14 h-14 bg-linear-to-br from-primary/20 to-primary-light/20 rounded-xl flex items-center justify-center shrink-0
```

**Checkmark** (feature lists):
```html
<div class="w-5 h-5 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0 mt-0.5">
  <svg class="w-3 h-3 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
  </svg>
</div>
```

---

## Responsive Breakpoints

Mobile-first approach. Key breakpoint: `md:` (768px).

| Pattern | Mobile | Desktop |
|---|---|---|
| Nav links | `hidden` | `md:flex` |
| Grids | `grid` (1 col) | `sm:grid-cols-2` or `md:grid-cols-3` |
| Hero text | `text-5xl` | `md:text-6xl lg:text-7xl` |
| Section layout | Stack | `md:flex` or `md:grid-cols-N` |
| Padding | `px-6` | Same (consistent) |

---

## Section Alternation

Alternate between dark and light backgrounds for visual rhythm:

```
Hero            → dark  (bg-dark, inherits body)
Trust Bar       → dark  (same section or thin strip)
Pain Points     → dark  (bg-dark)
Benefits        → light (bg-gray-50)
Process         → dark
Features        → light (bg-gray-50)
Pricing         → dark  (with radial glow)
Testimonials    → light (bg-gray-50)
FAQ             → light (bg-gray-50)
Final CTA       → dark  (with radial glow)
```

Adjust text colors accordingly:
- Dark sections: `text-white` headings, `text-slate-300` body
- Light sections: `text-gray-900` headings, `text-gray-600` body
