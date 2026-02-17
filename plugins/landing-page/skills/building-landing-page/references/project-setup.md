# Project Setup

Astro 5 + Tailwind v4 project scaffolding. Generate these files exactly.

## Contents
- File structure
- package.json
- astro.config.mjs
- tsconfig.json
- src/styles/global.css

---

## File Structure

```
project-root/
├── public/
│   └── favicon.svg
├── src/
│   ├── components/
│   │   ├── Navbar.astro
│   │   ├── Hero.astro
│   │   ├── TrustBar.astro
│   │   ├── PainPoints.astro
│   │   ├── Benefits.astro
│   │   ├── Process.astro
│   │   ├── Features.astro
│   │   ├── Pricing.astro
│   │   ├── Testimonials.astro
│   │   ├── FAQ.astro
│   │   ├── FinalCTA.astro
│   │   └── Footer.astro
│   ├── layouts/
│   │   └── Base.astro
│   ├── pages/
│   │   └── index.astro
│   └── styles/
│       └── global.css
├── astro.config.mjs
├── package.json
└── tsconfig.json
```

Only generate components for sections present in the copywriting input. Skip components for sections the user did not select.

---

## package.json

```json
{
  "name": "landing-page",
  "type": "module",
  "version": "0.1.0",
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview"
  },
  "dependencies": {
    "astro": "^5.17.1",
    "@astrojs/node": "^9.5.2",
    "@astrojs/sitemap": "^3.7.0",
    "tailwindcss": "^4.1.18",
    "@tailwindcss/vite": "^4.1.18"
  }
}
```

Adjust `"name"` to match the project name from user input.

---

## astro.config.mjs

```javascript
import { defineConfig } from "astro/config"
import node from "@astrojs/node"
import sitemap from "@astrojs/sitemap"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  site: "https://example.com",
  output: "server",
  adapter: node({ mode: "standalone" }),
  integrations: [sitemap()],
  vite: {
    plugins: [tailwindcss()],
  },
})
```

Replace `site` URL with the user's domain if provided.

---

## tsconfig.json

```json
{
  "extends": "astro/tsconfigs/strict",
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  }
}
```

---

## src/styles/global.css

```css
@import "tailwindcss";

@theme {
  --color-primary: #3b00ff;
  --color-primary-light: #604df5;
  --color-primary-dark: #2d00cc;
  --color-dark: #0a0a0f;
  --color-dark-lighter: #252d3d;
  --color-dark-border: #3d4a5c;
  --font-display: "Inter", system-ui, sans-serif;
}
```

Replace `--color-primary` values if the user specified a custom brand color. Derive `-light` (lighter 15%) and `-dark` (darker 15%) variants.
