# Frontend Overhaul — Task Plan

## Group A: Foundation (no cross-dependencies)

### Task 1: Web Fonts + Favicon + Meta
**Files**: templates/base.html
**Priority**: P0
- Add Google Fonts import for Inter (400,500,600,700) and JetBrains Mono (400,700)
- Add `<meta name="theme-color" content="#05070f">`
- Add favicon link (use an inline SVG data URI of a simple chart/trading icon)
- Add proper `<title>` blocks: each page should set its own title via `{% block title %}`

### Task 2: Responsive Design
**Files**: static/css/app.css
**Priority**: P0
- Add responsive breakpoints for mobile (<768px) and tablet (<1024px)
- `.container` padding: 36px 48px → 16px on mobile
- `.nav` should wrap or become a hamburger on mobile
- `.portfolio-summary`, `.config-cards`, `.account-meta` should stack single-column on mobile
- `.charts-container` should stack vertically on mobile
- Tables should get `overflow-x: auto` wrappers (already on trades, add globally)
- `.summaries-grid` min column width: 380px → 300px on mobile

### Task 3: Move Prompt Evolution Inline Styles to app.css
**Files**: templates/prompt_evolution.html, static/css/app.css
**Priority**: P1
- Extract all ~350 lines of `<style>` from prompt_evolution.html
- Move to app.css under a `/* Prompt Evolution */` section
- Remove the `<style>` block from the template
- Fix: prompt_evolution.html extends tabs.html instead of base.html — change to extend base.html for consistency

## Group B: UX Polish (parallel-safe)

### Task 4: Loading Skeletons + Auto-Refresh
**Files**: static/css/app.css, static/js/dashboard.js, templates/dashboard.html
**Priority**: P1
- Add CSS skeleton animation classes (`.skeleton`, `.skeleton-text`, `.skeleton-card`)
- Replace "Loading..." text in dashboard with skeleton placeholders
- Add auto-refresh on dashboard: poll `/api/holdings` every 60s, update metric cards without full page reload
- Add a subtle "Last updated: Xs ago" indicator near the top

### Task 5: Toast Notification System
**Files**: static/css/app.css, static/js/common.js, templates/base.html
**Priority**: P1
- Add a toast container div in base.html (fixed bottom-right)
- Add `showToast(message, type='info', durationMs=4000)` to common.js
- Types: success (green), error (red), info (blue), warning (yellow)
- Auto-dismiss with fade animation
- Replace inline trigger-status divs in dashboard.html with toast calls in dashboard.js

### Task 6: Trades Table Pagination + Today Filter Fix
**Files**: templates/trades.html, static/js/trades.js, static/css/app.css
**Priority**: P1
- Add client-side pagination: show 25 trades per page with prev/next buttons
- Fix daily summary: parse timestamps and count only today's trades (currently counts ALL)
- Add a "today only" quick filter chip
- Style pagination controls to match the dark theme

## Group C: Cleanup + Consistency

### Task 7: Dead Code + Template Consistency
**Files**: static/js/charts.js, templates/tabs.html, templates/prompt_evolution.html, templates/base.html
**Priority**: P1
- Delete static/js/charts.js (11 lines, unused — Chart.js is loaded directly)
- Unify templates: prompt_evolution.html should extend base.html (not tabs.html)
- If tabs.html is only used by prompt_evolution.html, delete it after migration
- Ensure all templates use `{% block title %}Page Name{% endblock %}`
- Remove all `style="display:none"` from templates → use a `.hidden` utility class in CSS

### Task 8: Accessibility Pass
**Files**: templates/base.html, static/css/app.css, all templates
**Priority**: P2
- Add skip-nav link in base.html
- Add `role="navigation"` to nav, `role="main"` to main
- Ensure all buttons have visible focus states (`:focus-visible` ring)
- Add `aria-label` to icon-only buttons (chart buttons, refresh)
- Add `aria-live="polite"` to status/toast regions
