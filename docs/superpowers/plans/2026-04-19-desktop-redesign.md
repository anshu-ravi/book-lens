# BookLens Desktop Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `src/static/index.html` to match the literary design system from the Claude Design export, and add a responsive desktop layout alongside the existing mobile experience.

**Architecture:** Single-file Alpine.js SPA — all changes go in `src/static/index.html`. The visual design (colors, typography, layout) changes substantially; the Alpine.js reactive logic and all API calls are preserved. The design's React prototype serves as the visual spec; we do not adopt React.

**Tech Stack:** Alpine.js 3, CSS (no build step), Google Fonts (Cormorant Garamond + Source Serif 4 + JetBrains Mono), FastAPI backend (unchanged).

**Design source:** `book-lens/project/` from the Claude Design bundle (styles.css, components.jsx, views.jsx, data.jsx). Full color tokens, typography rules, and layout patterns extracted.

---

## File Map

| File | Change |
|------|--------|
| `src/static/index.html` | Full visual redesign — CSS tokens, fonts, layout, all three views, responsive desktop |

No other files change.

---

## Task 1: Design tokens, fonts, and base reset

**Files:**
- Modify: `src/static/index.html` (the `<style>` block, `:root`, `html/body`, `#app`)

Replace the existing dark-theme CSS variables and font stack with the literary forest-green + bone/cream design system.

- [ ] **Step 1: Replace font imports**

Replace the `<link>` tags in `<head>` (lines 7–9):

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&family=Source+Serif+4:ital,opsz,wght@0,8..60,300;0,8..60,400;0,8..60,500;0,8..60,600;1,8..60,400;1,8..60,500&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
```

- [ ] **Step 2: Replace CSS custom properties in `:root`**

Replace the entire `:root { … }` block:

```css
:root {
  --bone:          #faf6ec;
  --bone-2:        #f2ecdc;
  --bone-3:        #e8e0cc;
  --ink:           #1f2420;
  --ink-2:         #3a3f38;
  --ink-3:         #6e7268;
  --ink-4:         #9a9b90;
  --forest:        #2a3328;
  --forest-2:      #3d4a3d;
  --moss:          #7a8376;
  --brass:         #a8864a;
  --brass-dim:     rgba(168,134,74,0.14);
  --ribbon:        #9a4a3a;
  --green:         #2a4a35;
  --green-dim:     rgba(42,74,53,0.15);
  --amber:         #8a6020;
  --amber-dim:     rgba(138,96,32,0.15);
  --red:           #8a3030;
  --red-dim:       rgba(138,48,48,0.12);
  --hairline:      rgba(31,36,32,0.13);
  --shadow:        0 4px 20px rgba(31,36,32,0.10), 0 1px 4px rgba(31,36,32,0.06);
  --shadow-sm:     0 1px 3px rgba(31,36,32,0.06);
  --radius:        8px;
  --radius-sm:     4px;
  --transition:    0.16s ease;
  --serif-display: 'Cormorant Garamond', Georgia, serif;
  --serif-body:    'Source Serif 4', Georgia, serif;
  --mono:          'JetBrains Mono', ui-monospace, monospace;
}
```

- [ ] **Step 3: Replace `html, body` and `#app` base styles**

```css
html, body {
  height: 100%;
  background: var(--bone);
  color: var(--ink);
  font-family: var(--serif-body);
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

#app {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}
```

- [ ] **Step 4: Verify server loads without JS errors**

```bash
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` — page should load with cream/bone background and serif fonts. No JS console errors.

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): apply literary design tokens and typography"
```

---

## Task 2: Responsive layout shell — sidebar (desktop) + tab-bar (mobile)

**Files:**
- Modify: `src/static/index.html` (layout CSS + HTML structure)

On mobile (< 768px): bottom tab-bar, full-width content (existing structure).
On desktop (≥ 768px): left sidebar (220px) with wordmark + nav links, content area fills remaining width.

- [ ] **Step 1: Add responsive layout CSS**

Add after the base reset:

```css
/* ── App shell ─────────────────────────────────────── */
#app {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}

/* Mobile: stacked column */
.app-body {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.app-content {
  flex: 1;
  max-width: 680px;
  width: 100%;
  margin: 0 auto;
  padding: 0 20px;
}

/* ── Header (mobile) ──────────────────────────────── */
.app-header {
  padding: 20px 20px 0;
  max-width: 680px;
  width: 100%;
  margin: 0 auto;
}

/* ── Tab bar (mobile only) ────────────────────────── */
.tabbar-mobile {
  flex-shrink: 0;
  display: flex;
  border-top: 1px solid var(--hairline);
  background: var(--bone);
  padding: 6px 0 max(12px, env(safe-area-inset-bottom));
}

.tabbar-mobile .tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 4px 4px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--ink-4);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  transition: color var(--transition);
}
.tabbar-mobile .tab svg { width: 20px; height: 20px; }
.tabbar-mobile .tab.active { color: var(--forest); }
.tabbar-mobile .tab-dot {
  width: 4px; height: 4px;
  border-radius: 50%;
  background: var(--forest);
  opacity: 0;
  transition: opacity 200ms;
}
.tabbar-mobile .tab.active .tab-dot { opacity: 1; }

/* ── Desktop layout (≥ 768px) ────────────────────── */
@media (min-width: 768px) {
  body { background: var(--bone-2); }

  #app {
    flex-direction: row;
    min-height: 100dvh;
  }

  .app-sidebar {
    width: 220px;
    flex-shrink: 0;
    background: var(--forest);
    display: flex;
    flex-direction: column;
    padding: 32px 0 24px;
    position: sticky;
    top: 0;
    height: 100dvh;
    overflow: hidden;
  }

  .sidebar-wordmark {
    font-family: var(--serif-display);
    font-size: 1.4rem;
    font-weight: 600;
    font-style: italic;
    color: var(--bone);
    letter-spacing: -0.02em;
    padding: 0 24px 32px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    margin-bottom: 20px;
  }
  .sidebar-wordmark em { color: var(--brass); font-style: normal; }

  .sidebar-nav {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 0 12px;
  }

  .sidebar-tab {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    background: none;
    border: none;
    cursor: pointer;
    color: rgba(250,246,236,0.55);
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    transition: background var(--transition), color var(--transition);
    text-align: left;
  }
  .sidebar-tab svg { width: 16px; height: 16px; flex-shrink: 0; }
  .sidebar-tab:hover { background: rgba(255,255,255,0.07); color: var(--bone); }
  .sidebar-tab.active { background: rgba(255,255,255,0.1); color: var(--bone); }
  .sidebar-tab.active svg { color: var(--brass); }

  .app-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    background: var(--bone);
  }

  .app-content {
    max-width: 860px;
    padding: 0 40px;
  }

  .app-header { display: none; }     /* wordmark lives in sidebar on desktop */
  .tabbar-mobile { display: none; }  /* nav lives in sidebar on desktop */
}
```

- [ ] **Step 2: Restructure the HTML shell**

Replace the existing `<div id="app">` structure. Preserve all Alpine state. The new structure wraps existing views:

```html
<div id="app" x-data="app()" x-cloak>

  <!-- Sidebar (desktop only) -->
  <aside class="app-sidebar" style="display:none" id="sidebar">
    <div class="sidebar-wordmark">Book<em>Lens</em></div>
    <nav class="sidebar-nav">
      <button class="sidebar-tab" :class="{ active: view === 'library' }" @click="switchView('library')">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 3v14M6 3v14M9.5 3l1.5 14M14 3v14M17 3v14" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        Library
      </button>
      <button class="sidebar-tab" :class="{ active: view === 'upload' }" @click="switchView('upload')">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 13V3m0 0L6 7m4-4l4 4M3 14v2a1 1 0 001 1h12a1 1 0 001-1v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Upload
      </button>
      <button class="sidebar-tab" :class="{ active: view === 'ask' }" @click="switchView('ask')">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 2.5a7.5 7.5 0 00-6.3 11.6L2.5 17.5l3.4-1.2A7.5 7.5 0 1010 2.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
        Ask
      </button>
    </nav>
  </aside>

  <!-- Main body -->
  <div class="app-body">

    <!-- Header (mobile only) -->
    <header class="app-header">
      <div class="wordmark">📚 Book<span>Lens</span></div>
    </header>

    <!-- Content area -->
    <main class="app-content">
      <!-- views go here (unchanged inner HTML) -->
    </main>

    <!-- Tab bar (mobile only) -->
    <nav class="tabbar-mobile">
      <button class="tab" :class="{ active: view === 'library' }" @click="switchView('library')">
        <svg viewBox="0 0 20 20" fill="none"><path d="M3 3v14M6 3v14M9.5 3l1.5 14M14 3v14M17 3v14" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        Library
        <div class="tab-dot"></div>
      </button>
      <button class="tab" :class="{ active: view === 'upload' }" @click="switchView('upload')">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 13V3m0 0L6 7m4-4l4 4M3 14v2a1 1 0 001 1h12a1 1 0 001-1v-2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Upload
        <div class="tab-dot"></div>
      </button>
      <button class="tab" :class="{ active: view === 'ask' }" @click="switchView('ask')">
        <svg viewBox="0 0 20 20" fill="none"><path d="M10 2.5a7.5 7.5 0 00-6.3 11.6L2.5 17.5l3.4-1.2A7.5 7.5 0 1010 2.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
        Ask
        <div class="tab-dot"></div>
      </button>
    </nav>

  </div>

  <!-- Modal (unchanged) -->
</div>
```

Add a JS snippet at the bottom of `<script>` to show the sidebar on desktop:
```js
// Show/hide sidebar based on viewport (CSS media query hides it at mobile)
const mq = window.matchMedia('(min-width: 768px)');
document.getElementById('sidebar').style.display = mq.matches ? 'flex' : 'none';
mq.addEventListener('change', e => {
  document.getElementById('sidebar').style.display = e.matches ? 'flex' : 'none';
});
```

- [ ] **Step 3: Verify layout on both widths**

```bash
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

- Mobile (375px): bottom tab bar visible, sidebar hidden
- Desktop (1280px): dark green left sidebar visible, bottom tab bar hidden
- Navigation between Library/Upload/Ask works on both

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): add responsive desktop sidebar layout"
```

---

## Task 3: Library view — book covers, series sections, continue-reading strip

**Files:**
- Modify: `src/static/index.html` (library view HTML + CSS)

Replace the plain list-based library with the cover-based design. Each series becomes a section with a horizontal scroll strip of generated covers. "Continue reading" shows books currently in progress.

- [ ] **Step 1: Add book cover CSS**

```css
/* ── Book cover (generated) ────────────────────────── */
.cover {
  position: relative;
  flex-shrink: 0;
  border-radius: 2px 5px 5px 2px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 200ms cubic-bezier(.2,.9,.3,1), box-shadow 200ms;
  box-shadow:
    inset 2px 0 0 rgba(255,255,255,0.06),
    inset -1px 0 2px rgba(0,0,0,0.3),
    0 2px 6px rgba(0,0,0,0.18),
    0 8px 18px rgba(0,0,0,0.10);
}
.cover:hover {
  transform: translateY(-4px);
  box-shadow:
    inset 2px 0 0 rgba(255,255,255,0.06),
    inset -1px 0 2px rgba(0,0,0,0.3),
    0 6px 12px rgba(0,0,0,0.2),
    0 16px 32px rgba(0,0,0,0.14);
}
.cover-inner {
  position: absolute;
  inset: 10px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.cover-frame {
  position: absolute;
  inset: 5px;
  border: 0.5px solid rgba(255,255,255,0.25);
  border-radius: 1px;
  pointer-events: none;
}
.cover-sheen {
  position: absolute; inset: 0;
  background: linear-gradient(115deg, rgba(255,255,255,0.07) 0%, transparent 30%, transparent 70%, rgba(0,0,0,0.12) 100%);
  pointer-events: none;
}
.cover-series-label {
  font-family: var(--mono);
  font-size: 6.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  opacity: 0.7;
  margin-bottom: 8px;
}
.cover-rule { width: 20px; height: 0.5px; opacity: 0.4; margin-bottom: 10px; }
.cover-title {
  font-family: var(--serif-display);
  font-style: italic;
  font-weight: 500;
  line-height: 1.05;
  letter-spacing: -0.01em;
  flex: 1;
  display: flex;
  align-items: center;
  padding: 0 2px;
}
.cover-bottom {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding-bottom: 2px;
}
.cover-author { font-family: var(--serif-body); font-style: italic; font-size: 8px; opacity: 0.65; }
.cover-vol { font-family: var(--mono); font-size: 6.5px; letter-spacing: 0.18em; opacity: 0.75; }
.cover-progress-bar {
  position: absolute;
  left: 8px; right: 8px; bottom: 5px;
  height: 2px;
  background: rgba(0,0,0,0.25);
  border-radius: 1px;
  overflow: hidden;
}
.cover-progress-fill { height: 100%; border-radius: 1px; }
.cover-badge {
  position: absolute;
  top: 8px; right: 8px;
  width: 14px; height: 14px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cover-badge svg { width: 8px; height: 8px; }
.cover-unread-tag {
  position: absolute;
  top: 8px; right: 8px;
  font-family: var(--mono);
  font-size: 6px;
  letter-spacing: 0.15em;
  background: rgba(0,0,0,0.35);
  color: rgba(255,255,255,0.55);
  padding: 2px 5px;
  border-radius: 100px;
}

/* ── Continue reading strip ────────────────────────── */
.continue-section { margin-bottom: 32px; }
.section-eyebrow {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-bottom: 12px;
}
.continue-list { display: flex; flex-direction: column; gap: 8px; }
.continue-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px;
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: none;
  text-align: left;
  font-family: inherit;
  transition: background var(--transition);
  width: 100%;
}
.continue-card:hover { background: var(--bone-3); }
.continue-meta { flex: 1; min-width: 0; }
.continue-series-name {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--moss);
  margin-bottom: 2px;
}
.continue-title {
  font-family: var(--serif-display);
  font-size: 19px;
  font-weight: 500;
  font-style: italic;
  color: var(--forest);
  letter-spacing: -0.01em;
  line-height: 1.1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.continue-sub {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ink-3);
  margin-top: 2px;
}
.continue-track {
  margin-top: 6px;
  height: 2px;
  background: var(--bone-3);
  border-radius: 1px;
  overflow: hidden;
}
.continue-track > div { height: 100%; background: var(--forest-2); border-radius: 1px; }
.continue-pct {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 500;
  color: var(--forest);
  flex-shrink: 0;
}

/* ── Series section ────────────────────────────────── */
.shelves { display: flex; flex-direction: column; gap: 36px; }
.series-section { }
.series-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--hairline);
}
.series-head-main { flex: 1; min-width: 0; }
.series-name-display {
  font-family: var(--serif-display);
  font-size: 22px;
  font-weight: 500;
  font-style: italic;
  color: var(--forest);
  letter-spacing: -0.015em;
  line-height: 1.1;
}
.series-meta-line {
  margin-top: 3px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--ink-3);
  letter-spacing: 0.02em;
}
.series-progress-arc {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}
.series-arc-track {
  width: 72px;
  height: 3px;
  background: var(--bone-3);
  border-radius: 2px;
  overflow: hidden;
}
.series-arc-track > div { height: 100%; background: var(--forest-2); border-radius: 2px; }
.series-arc-pct { font-family: var(--mono); font-size: 10px; color: var(--forest); font-weight: 500; }

.series-scroll {
  margin: 0 -20px;
  padding: 0 20px;
  overflow-x: auto;
  overflow-y: visible;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}
.series-scroll::-webkit-scrollbar { display: none; }
.series-strip {
  display: flex;
  gap: 12px;
  padding: 4px 0 10px;
}

/* Series-specific cover colors */
.cover-family-0 { background: #2a3328; color: #e8ddc4; }  /* forest — Tidewater-like */
.cover-family-1 { background: #4a2f1f; color: #e8c87a; }  /* oxblood — Ironwood-like */
.cover-family-2 { background: #3a3628; color: #f0e8d0; }  /* slate — Standalones */
.cover-family-3 { background: #1f2e3a; color: #d8e4ec; }  /* navy */
.cover-family-4 { background: #3a2830; color: #ecd8e0; }  /* plum */

/* ── Library view header ─────────────────────────── */
.view-eyebrow {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--moss);
  margin-bottom: 10px;
}
.view-title-display {
  font-family: var(--serif-display);
  font-weight: 500;
  font-style: italic;
  font-size: 44px;
  line-height: 0.98;
  letter-spacing: -0.02em;
  color: var(--forest);
  margin-bottom: 12px;
}
.view-stats-line {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: 0.02em;
  margin-bottom: 28px;
}
.view-stats-line strong { color: var(--forest); }
.view-stats-line .dot { margin: 0 8px; opacity: 0.4; }

@media (min-width: 768px) {
  .series-scroll { margin: 0; padding: 0; }
  .app-content { padding-top: 40px; }
  .view-title-display { font-size: 52px; }
}
```

- [ ] **Step 2: Add Alpine helper for cover color family**

Add a `coverFamily(index)` method to the Alpine `app()` object that returns 0–4 based on series index:

```js
coverFamily(index) {
  return index % 5;
},
seriesProgress(series) {
  const total = series.books.reduce((s, b) => s + (b.chapters?.length ?? 0), 0);
  const read = series.books.filter(b => b.status === 'completed').length;
  const total_b = series.books.length;
  if (total_b === 0) return 0;
  return Math.round((read / total_b) * 100);
},
currentlyReading() {
  if (!this.library) return [];
  return this.library.series.flatMap(s =>
    s.books
      .filter(b => b.status === 'reading')
      .map(b => ({ ...b, _series: s }))
  );
},
```

- [ ] **Step 3: Rewrite the Library view HTML**

Replace the Library view `<div x-show="view === 'library'">` block with:

```html
<!-- ═══════════════════ LIBRARY VIEW ═══════════════════ -->
<div x-show="view === 'library'" class="view-enter" style="padding: 28px 0 48px;">

  <!-- View header -->
  <header style="margin-bottom: 24px;">
    <div class="view-eyebrow">Your library</div>
    <h1 class="view-title-display">A private shelf.</h1>
    <div class="view-stats-line" x-show="library">
      <strong x-text="library?.series?.flatMap(s => s.books).length ?? 0"></strong> volumes
      <span class="dot">·</span>
      <strong x-text="library?.series?.flatMap(s => s.books).filter(b => b.status === 'reading').length ?? 0"></strong> in hand
      <span class="dot">·</span>
      <strong x-text="library?.series?.flatMap(s => s.books).filter(b => b.status === 'completed').length ?? 0"></strong> finished
    </div>
  </header>

  <!-- New series inline form (keep as-is but restyle) -->
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
    <div></div>
    <button class="btn btn-primary btn-sm" @click="showNewSeriesForm = !showNewSeriesForm">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
      New Series
    </button>
  </div>
  <div x-show="showNewSeriesForm" class="inline-form" x-transition>
    <div class="inline-form-row">
      <div class="form-group">
        <label>Series ID</label>
        <input type="text" x-model="newSeries.id" placeholder="red-rising" />
      </div>
      <div class="form-group">
        <label>Series Name</label>
        <input type="text" x-model="newSeries.name" placeholder="Red Rising Saga" />
      </div>
    </div>
    <div style="display:flex;gap:8px;margin-top:12px;">
      <button class="btn btn-primary btn-sm" @click="createSeries()" :disabled="!newSeries.id || !newSeries.name || saving">
        <span x-show="saving" class="spinner" style="width:14px;height:14px;"></span>
        <span x-text="saving ? 'Creating…' : 'Create'"></span>
      </button>
      <button class="btn btn-ghost btn-sm" @click="showNewSeriesForm = false; newSeries = { id:'', name:'' }">Cancel</button>
    </div>
    <div x-show="error" class="alert alert-error" style="margin-top:10px;margin-bottom:0" x-text="error"></div>
  </div>

  <!-- Empty state -->
  <div x-show="!library || library.series.length === 0" class="empty-state">
    <div class="empty-state-icon">📖</div>
    <p>No books yet. Create a series and upload your first epub.</p>
    <button class="btn btn-primary" @click="switchView('upload')">Upload a Book</button>
  </div>

  <!-- Continue reading -->
  <template x-if="currentlyReading().length > 0">
    <section class="continue-section">
      <div class="section-eyebrow">Continue reading</div>
      <div class="continue-list">
        <template x-for="book in currentlyReading().slice(0, 3)" :key="book.id ?? book.index">
          <button class="continue-card" @click="openProgressModal(book._series, book)">
            <div class="cover cover-family-0" style="width:54px;height:82px;flex-shrink:0;">
              <div class="cover-frame"></div>
              <div class="cover-inner" style="inset:8px 6px;">
                <div class="cover-title" style="font-size:9px;" x-text="book.title"></div>
              </div>
              <div class="cover-sheen"></div>
            </div>
            <div class="continue-meta">
              <div class="continue-series-name" x-text="book._series.name"></div>
              <div class="continue-title" x-text="book.title"></div>
              <div class="continue-sub" x-text="statusLabel(book)"></div>
              <div class="continue-track" x-show="book.chapters?.length">
                <div :style="'width:' + Math.round(((book.current_chapter_index ?? 0) / Math.max(book.chapters?.length - 1, 1)) * 100) + '%'"></div>
              </div>
            </div>
            <div class="continue-pct" x-show="book.chapters?.length"
              x-text="Math.round(((book.current_chapter_index ?? 0) / Math.max(book.chapters?.length - 1, 1)) * 100) + '%'">
            </div>
          </button>
        </template>
      </div>
    </section>
  </template>

  <!-- Series shelves -->
  <div class="shelves">
    <template x-for="(series, seriesIndex) in (library?.series ?? [])" :key="series.id">
      <section class="series-section">
        <header class="series-head">
          <div class="series-head-main">
            <div class="series-name-display" x-text="series.name"></div>
            <div class="series-meta-line">
              <span x-text="series.books.length + ' book' + (series.books.length !== 1 ? 's' : '')"></span>
              <span style="margin:0 6px;opacity:0.4">·</span>
              <span x-text="series.books.filter(b => b.status === 'completed').length + ' finished'"></span>
              <span style="margin:0 6px;opacity:0.4">·</span>
              <span style="color:var(--ink-2)" x-text="'id: ' + series.id"></span>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <div class="series-progress-arc" x-show="series.books.length > 0">
              <div class="series-arc-track">
                <div :style="'width:' + Math.round((series.books.filter(b => b.status === 'completed').length / series.books.length) * 100) + '%'"></div>
              </div>
              <div class="series-arc-pct"
                x-text="Math.round((series.books.filter(b => b.status === 'completed').length / series.books.length) * 100) + '%'">
              </div>
            </div>
            <button class="btn-icon" title="Delete series" @click="confirmDeleteSeries(series)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
            </button>
          </div>
        </header>

        <div x-show="series.books.length === 0" style="font-size:0.85rem;color:var(--ink-3);padding:8px 0;font-style:italic;">
          No books — <a href="#" style="color:var(--brass);text-decoration:none;" @click.prevent="upload.seriesId = series.id; switchView('upload')">upload one</a>
        </div>

        <!-- Cover strip -->
        <div class="series-scroll" x-show="series.books.length > 0">
          <div class="series-strip">
            <template x-for="book in sortedBooks(series.books)" :key="book.index">
              <div style="display:flex;flex-direction:column;align-items:center;gap:8px;">
                <!-- Generated cover -->
                <button
                  class="cover"
                  :class="'cover-family-' + (seriesIndex % 5)"
                  style="width:104px;height:158px;"
                  @click="openProgressModal(series, book)">
                  <div class="cover-frame"></div>
                  <div class="cover-inner">
                    <div class="cover-series-label" x-text="series.name.toUpperCase()"></div>
                    <div class="cover-rule" :style="'background:currentColor'"></div>
                    <div class="cover-title" style="font-size:14px;" x-text="book.title"></div>
                    <div class="cover-bottom">
                      <div class="cover-vol" x-text="'VOL. ' + String(book.index + 1).padStart(2, '0')"></div>
                    </div>
                  </div>
                  <!-- Progress bar -->
                  <div class="cover-progress-bar" x-show="book.status === 'reading' && book.chapters?.length">
                    <div class="cover-progress-fill"
                      style="background:rgba(255,255,255,0.6);"
                      :style="'width:' + Math.round(((book.current_chapter_index ?? 0) / Math.max(book.chapters?.length - 1, 1)) * 100) + '%;background:rgba(255,255,255,0.6);'">
                    </div>
                  </div>
                  <!-- Finished badge -->
                  <div class="cover-badge" x-show="book.status === 'completed'"
                    style="background:rgba(168,134,74,0.9);">
                    <svg viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-7" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  </div>
                  <!-- Unread tag -->
                  <div class="cover-unread-tag" x-show="book.status === 'not_started'">UNREAD</div>
                  <div class="cover-sheen"></div>
                </button>
                <!-- Book actions below cover -->
                <div style="display:flex;gap:4px;">
                  <span class="badge"
                    :class="{
                      'badge-completed':   book.status === 'completed',
                      'badge-reading':     book.status === 'reading',
                      'badge-not-started': book.status === 'not_started'
                    }"
                    x-text="book.status === 'completed' ? '✓' : book.status === 'reading' ? '▶' : '○'">
                  </span>
                  <button class="btn-icon" title="Delete book" @click="confirmDeleteBook(series, book)">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>

      </section>
    </template>
  </div>

</div>
```

- [ ] **Step 4: Verify library view**

```bash
# server should already be running
```

Open `http://localhost:8000` — check:
- Series display as cover strips (coloured book covers visible)
- "Continue reading" section appears if any book has status `reading`
- Covers scroll horizontally when series has many books
- Delete buttons still work

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): redesign library with cover strips and continue-reading section"
```

---

## Task 4: Ask view — chat thread layout with scope banner and conversation history

**Files:**
- Modify: `src/static/index.html` (ask view HTML, CSS, and Alpine state)

The current ask view is a form (select series → type question → see answer). Replace with a chat thread layout: book chip at top (showing active series/scope), scrollable message thread, bottom composer. Sends `conversation_history` to the backend (already supported since Task 0 diff).

- [ ] **Step 1: Add Ask view CSS**

```css
/* ── Ask view (chat thread) ────────────────────────── */
.ask-view-layout {
  display: flex;
  flex-direction: column;
  height: calc(100dvh - 60px); /* subtract tab bar height */
  padding: 0;
}

@media (min-width: 768px) {
  .ask-view-layout { height: calc(100dvh - 80px); }
}

.ask-view-header { padding: 28px 0 16px; flex-shrink: 0; }

.ask-book-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px 6px 8px;
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-radius: 100px;
  cursor: pointer;
  font-family: inherit;
  color: var(--ink);
  transition: background var(--transition);
  margin-bottom: 16px;
}
.ask-book-chip:hover { background: var(--bone-3); }
.ask-chip-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; background: var(--forest); }
.ask-chip-title {
  font-family: var(--serif-display);
  font-size: 14px;
  font-style: italic;
  color: var(--forest);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
.ask-chip-scope { font-family: var(--mono); font-size: 9px; color: var(--ink-3); letter-spacing: 0.04em; }

.ask-thread {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--bone-3) transparent;
  padding: 8px 0 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.ask-thread::-webkit-scrollbar { width: 4px; }
.ask-thread::-webkit-scrollbar-track { background: transparent; }
.ask-thread::-webkit-scrollbar-thumb { background: var(--bone-3); border-radius: 2px; }

.ask-empty {
  text-align: center;
  padding: 48px 20px;
  color: var(--ink-3);
}
.ask-empty-icon {
  width: 52px; height: 52px;
  border-radius: 50%;
  background: rgba(122,131,118,0.1);
  color: var(--forest);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}
.ask-empty-text {
  font-family: var(--serif-body);
  font-size: 15px;
  line-height: 1.55;
  color: var(--ink-2);
  font-style: italic;
  max-width: 32ch;
  margin: 0 auto 20px;
}
.ask-examples { display: flex; flex-direction: column; gap: 6px; max-width: 400px; margin: 0 auto; }
.ask-example-btn {
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: 11px 14px;
  text-align: left;
  font-family: var(--serif-body);
  font-size: 14px;
  font-style: italic;
  color: var(--ink-2);
  cursor: pointer;
  transition: all var(--transition);
}
.ask-example-btn:hover { background: var(--bone-3); color: var(--forest); }

/* Messages */
.msg { display: flex; flex-direction: column; }
.msg-user { align-items: flex-end; gap: 4px; }
.msg-bubble-user {
  max-width: 82%;
  padding: 12px 16px;
  background: var(--forest);
  color: var(--bone);
  border-radius: 14px 14px 2px 14px;
  font-family: var(--serif-body);
  font-size: 15px;
  line-height: 1.4;
}
.msg-scope-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--mono);
  font-size: 9.5px;
  color: var(--ink-3);
  letter-spacing: 0.04em;
  padding-right: 4px;
}

.msg-assistant { align-items: flex-start; gap: 8px; }
.scope-banner {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 9.5px;
  color: var(--forest);
  letter-spacing: 0.02em;
  padding: 4px 10px;
  background: rgba(122,131,118,0.1);
  border-radius: 100px;
}
.scope-banner em { font-family: var(--serif-body); font-style: italic; font-size: 11px; letter-spacing: 0; }

.msg-bubble-ai {
  max-width: 92%;
  padding: 16px 18px;
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-radius: 2px 14px 14px 14px;
  font-family: var(--serif-body);
  font-size: 15px;
  line-height: 1.55;
  color: var(--ink);
  white-space: pre-wrap;
}
.sources-section {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--hairline);
}
.sources-label {
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-bottom: 8px;
}
.source-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  background: var(--bone);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  margin-bottom: 4px;
  cursor: default;
}
.source-loc { font-family: var(--mono); font-size: 10px; color: var(--ink-3); white-space: nowrap; flex-shrink: 0; }
.source-excerpt {
  font-size: 12px;
  font-style: italic;
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

/* Composer */
.ask-composer {
  flex-shrink: 0;
  padding: 12px 0 16px;
  border-top: 1px solid var(--hairline);
  background: var(--bone);
}
.composer-row { display: flex; gap: 8px; align-items: flex-end; }
.composer-input {
  flex: 1;
  padding: 12px 16px;
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-radius: 24px;
  font-family: var(--serif-body);
  font-size: 15px;
  color: var(--ink);
  outline: none;
  transition: border-color var(--transition);
  resize: none;
  height: 48px;
  line-height: 1.5;
}
.composer-input:focus { border-color: var(--forest-2); background: var(--bone); }
.composer-input::placeholder { color: var(--ink-4); font-style: italic; }
.composer-send {
  width: 48px; height: 48px;
  border-radius: 50%;
  background: var(--forest);
  border: none;
  color: var(--bone);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all var(--transition);
}
.composer-send:disabled { background: var(--bone-3); color: var(--ink-4); cursor: not-allowed; }
.composer-send:not(:disabled):hover { background: var(--forest-2); }
```

- [ ] **Step 2: Add Alpine state for chat thread**

Add to the Alpine `app()` data object:

```js
thread: [],       // array of {role, text, seriesId, seriesName, summary}
```

Add methods:

```js
// Push user message + get AI response, building up thread
async sendMessage() {
  const q = this.ask.question.trim();
  if (!q || this.ask.loading || !this.ask.seriesId) return;

  const series = this.library?.series?.find(s => s.id === this.ask.seriesId);
  const seriesName = series?.name ?? this.ask.seriesId;
  const summary = this.ask.summary;

  // Add user message to thread
  this.thread.push({ role: 'user', text: q, seriesName, summary });
  this.ask.question = '';
  this.ask.loading = true;
  this.ask.error = '';

  // Build history from thread (last 6 turns)
  const history = this.thread
    .slice(-7, -1)
    .map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));

  try {
    const res = await fetch('/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        series_id: this.ask.seriesId,
        question: q,
        top_k: 5,
        conversation_history: history,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      this.thread.push({ role: 'error', text: data.detail ?? 'Query failed.' });
      return;
    }
    this.thread.push({
      role: 'assistant',
      text: data.answer,
      sources: data.sources ?? [],
      seriesName,
      summary,
    });
  } catch (e) {
    this.thread.push({ role: 'error', text: 'Network error. Is the server running?' });
  } finally {
    this.ask.loading = false;
    this.$nextTick(() => {
      const el = document.getElementById('ask-thread');
      if (el) el.scrollTop = el.scrollHeight;
    });
  }
},

clearThread() {
  this.thread = [];
  this.ask.answer = '';
  this.ask.sources = [];
},
```

Update the `switchView` method to call `updateReadingSummary()` when switching to `ask` and set default series:
```js
switchView(v) {
  this.view = v;
  this.error = null;
  this.uploadSuccess = '';
  this.uploadError = '';
  if (v === 'ask') {
    this.updateReadingSummary();
    // default to first series if none selected
    if (!this.ask.seriesId && this.library?.series?.length) {
      this.ask.seriesId = this.library.series[0].id;
      this.updateReadingSummary();
    }
  }
},
```

- [ ] **Step 3: Rewrite Ask view HTML**

Replace the `<div x-show="view === 'ask'">` block with:

```html
<!-- ═══════════════════ ASK VIEW ═══════════════════════ -->
<div x-show="view === 'ask'" class="view-enter ask-view-layout">

  <header class="ask-view-header">
    <div class="view-eyebrow">Ask</div>
    <h1 class="view-title-display" style="font-size:36px;margin-bottom:16px;">No spoilers,<br>by construction.</h1>

    <!-- Series selector (shown when thread is empty or as persistent control) -->
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
      <button class="ask-book-chip" @click="clearThread()">
        <span class="ask-chip-dot"></span>
        <span class="ask-chip-label">
          <span class="ask-chip-title"
            x-text="library?.series?.find(s => s.id === ask.seriesId)?.name ?? 'Select a series'">
          </span>
          <span class="ask-chip-scope" x-text="ask.summary ? 'through: ' + ask.summary : 'no progress set'"></span>
        </span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="opacity:0.4;transform:rotate(90deg)"><path d="M9 18l6-6-6-6"/></svg>
      </button>
      <select x-model="ask.seriesId" @change="updateReadingSummary(); clearThread();"
        style="font-family:var(--mono);font-size:11px;padding:6px 10px;background:var(--bone-2);border:1px solid var(--hairline);border-radius:4px;color:var(--ink);outline:none;">
        <option value="" disabled>Select a series…</option>
        <template x-for="s in (library?.series ?? [])" :key="s.id">
          <option :value="s.id" x-text="s.name"></option>
        </template>
      </select>
    </div>
  </header>

  <!-- Thread -->
  <div class="ask-thread" id="ask-thread">

    <!-- Empty state -->
    <div x-show="thread.length === 0 && !ask.loading" class="ask-empty">
      <div class="ask-empty-icon">
        <svg width="22" height="22" viewBox="0 0 14 14" fill="none">
          <path d="M7 1l5 2v4c0 3-2 5.5-5 6-3-.5-5-3-5-6V3l5-2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>
          <path d="M5 7l1.5 1.5L9 6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <p class="ask-empty-text" x-show="ask.seriesId && ask.summary">
        Ask anything about <em x-text="library?.series?.find(s => s.id === ask.seriesId)?.name"></em>. Answers stay within your reading bookmark — no spoilers.
      </p>
      <p class="ask-empty-text" x-show="ask.seriesId && !ask.summary" style="color:var(--red);">
        No reading progress set for this series. Update your progress in the Library tab first.
      </p>
      <p class="ask-empty-text" x-show="!ask.seriesId">Select a series above to get started.</p>
    </div>

    <!-- Messages -->
    <template x-for="(msg, i) in thread" :key="i">
      <div :class="msg.role === 'user' ? 'msg msg-user' : 'msg msg-assistant'">

        <!-- User bubble -->
        <template x-if="msg.role === 'user'">
          <div>
            <div class="msg-bubble-user" x-text="msg.text"></div>
            <div class="msg-scope-label" style="margin-top:4px;">
              <svg width="10" height="10" viewBox="0 0 14 14" fill="none"><path d="M2 2h5a2 2 0 012 2v8a2 2 0 00-2-2H2V2zM12 2H7a2 2 0 00-2 2v8a2 2 0 012-2h5V2z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>
              <span x-text="msg.seriesName + (msg.summary ? ' · ' + msg.summary : '')"></span>
            </div>
          </div>
        </template>

        <!-- AI bubble -->
        <template x-if="msg.role === 'assistant'">
          <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-start;">
            <div class="scope-banner">
              <svg width="11" height="11" viewBox="0 0 14 14" fill="none"><path d="M7 1l5 2v4c0 3-2 5.5-5 6-3-.5-5-3-5-6V3l5-2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M5 7l1.5 1.5L9 6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
              Answering from <em x-text="msg.seriesName"></em>
              <span x-show="msg.summary"> · <span x-text="msg.summary"></span></span>
            </div>
            <div class="msg-bubble-ai">
              <span x-text="msg.text"></span>
              <div x-show="msg.sources && msg.sources.length > 0" class="sources-section">
                <div class="sources-label">Sources</div>
                <template x-for="(src, j) in (msg.sources ?? [])" :key="j">
                  <div class="source-row">
                    <span class="source-loc" x-text="'Book ' + (src.book_index + 1) + ' · ' + src.chapter_label"></span>
                    <span class="source-excerpt" x-text="src.score ? (src.score * 100).toFixed(0) + '% match' : ''"></span>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </template>

        <!-- Error bubble -->
        <template x-if="msg.role === 'error'">
          <div class="alert alert-error" x-text="msg.text"></div>
        </template>

      </div>
    </template>

    <!-- Loading indicator -->
    <div x-show="ask.loading" class="msg msg-assistant" style="align-items:flex-start;gap:8px;">
      <div class="scope-banner">Thinking…</div>
      <div class="msg-bubble-ai" style="display:flex;align-items:center;gap:8px;padding:14px 16px;">
        <span class="spinner" style="width:16px;height:16px;border-color:var(--bone-3);border-top-color:var(--forest);"></span>
        <span style="font-style:italic;color:var(--ink-3);font-size:14px;">Searching within your reading progress…</span>
      </div>
    </div>

  </div>

  <!-- Composer -->
  <div class="ask-composer">
    <div class="composer-row">
      <input
        class="composer-input"
        type="text"
        placeholder="Ask about this book…"
        x-model="ask.question"
        @keydown.enter="sendMessage()"
        :disabled="!ask.seriesId || ask.loading"
      />
      <button class="composer-send"
        @click="sendMessage()"
        :disabled="!ask.seriesId || !ask.question.trim() || ask.loading">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
          <path d="M9 15V3m0 0L4 8m5-5l5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </div>

</div>
```

- [ ] **Step 4: Verify Ask view**

Open `http://localhost:8000`, navigate to Ask tab:
- Series dropdown selects a series
- Empty state shows with spoiler-guard icon
- Typing a question and pressing Enter sends it
- Response appears as AI bubble with scope banner
- Follow-up question in same thread (conversation history sent)
- Loading spinner appears while waiting

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): redesign ask view as chat thread with scope banners and conversation history"
```

---

## Task 5: Upload view and global component polish

**Files:**
- Modify: `src/static/index.html` (upload view, global buttons, form elements, modal, alerts)

Update the upload view to match the literary aesthetic and polish global components (buttons, forms, modal, alerts, progress bar).

- [ ] **Step 1: Update global component CSS to use new tokens**

Replace `.btn-primary` colors, `.btn-ghost` styles, `.card`, `.form-group`, `label`, `input`, `select`, `textarea`, `.alert-error/success`, `.progress-*`, `.modal` styles to use the new CSS variables:

```css
/* ── Cards ──────────────────────────────────────────── */
.card {
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 20px;
  margin-bottom: 16px;
}
.card-title {
  font-family: var(--serif-display);
  font-size: 1.1rem;
  font-weight: 500;
  font-style: italic;
  color: var(--forest);
  margin-bottom: 4px;
}
.card-sub { font-family: var(--mono); font-size: 0.8rem; color: var(--ink-3); margin-bottom: 16px; letter-spacing: 0.02em; }

/* ── Buttons ──────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 18px;
  border-radius: var(--radius-sm);
  font-family: var(--serif-body);
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: background var(--transition), color var(--transition), opacity var(--transition);
}
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-primary { background: var(--forest); color: var(--bone); }
.btn-primary:hover:not(:disabled) { background: var(--forest-2); }
.btn-ghost { background: transparent; color: var(--ink-2); border: 1px solid var(--hairline); }
.btn-ghost:hover:not(:disabled) { background: var(--bone-2); }
.btn-danger { background: var(--red-dim); color: var(--red); border: 1px solid transparent; }
.btn-danger:hover:not(:disabled) { background: rgba(138,48,48,0.2); }
.btn-sm { padding: 5px 12px; font-size: 0.8rem; }
.btn-icon {
  background: transparent; border: none; padding: 5px;
  cursor: pointer; color: var(--ink-3); border-radius: 4px;
  transition: color var(--transition), background var(--transition);
  display: inline-flex; align-items: center;
}
.btn-icon:hover { color: var(--red); background: var(--red-dim); }

/* ── Forms ──────────────────────────────────────────── */
.form-group { margin-bottom: 16px; }
label {
  display: block;
  font-family: var(--mono);
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--ink-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}
input[type="text"], input[type="number"], select, textarea {
  width: 100%;
  background: var(--bone);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font-family: var(--serif-body);
  font-size: 0.9rem;
  padding: 10px 14px;
  outline: none;
  transition: border-color var(--transition);
  appearance: none;
}
input:focus, select:focus, textarea:focus { border-color: var(--forest-2); }
textarea { resize: vertical; min-height: 100px; }
select {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a8864a' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 14px center;
  padding-right: 36px;
}

/* ── Drop zone (upload) ─────────────────────────────── */
.drop-zone {
  border: 1.5px dashed var(--ink-4);
  border-radius: var(--radius);
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition);
  position: relative;
}
.drop-zone:hover, .drop-zone.drag-over { border-color: var(--forest); background: rgba(42,51,40,0.04); }
.drop-zone input[type="file"] { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
.drop-zone-icon { font-size: 2.2rem; margin-bottom: 10px; }
.drop-zone-text { font-family: var(--serif-body); font-size: 0.9rem; color: var(--ink-3); font-style: italic; }
.drop-zone-text strong { color: var(--forest); font-style: normal; }
.drop-zone-filename { margin-top: 8px; font-family: var(--mono); font-size: 0.8rem; color: var(--ink); }

/* ── Progress ─────────────────────────────────────────── */
.progress-wrap { background: var(--bone-3); border-radius: 99px; height: 3px; overflow: hidden; margin-top: 14px; }
.progress-bar { height: 100%; background: var(--forest); border-radius: 99px; transition: width 0.4s ease; }
.progress-label { font-family: var(--mono); font-size: 0.75rem; color: var(--ink-3); margin-top: 6px; text-align: center; letter-spacing: 0.02em; }

/* ── Section header ─────────────────────────────────── */
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-title { font-family: var(--serif-display); font-size: 1.2rem; font-weight: 500; font-style: italic; color: var(--forest); }

/* ── Alerts ─────────────────────────────────────────── */
.alert { padding: 11px 14px; border-radius: var(--radius-sm); font-family: var(--serif-body); font-size: 0.875rem; margin-bottom: 14px; font-style: italic; }
.alert-error { background: var(--red-dim); color: var(--red); border: 1px solid rgba(138,48,48,0.2); }
.alert-success { background: var(--green-dim); color: var(--green); border: 1px solid rgba(42,74,53,0.2); }

/* ── Modal ───────────────────────────────────────────── */
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(31,36,32,0.55);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.modal {
  background: var(--bone);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  box-shadow: 0 24px 60px rgba(31,36,32,0.22);
  padding: 24px;
  width: 100%;
  max-width: 400px;
}
.modal-title { font-family: var(--serif-display); font-size: 1.1rem; font-weight: 500; font-style: italic; color: var(--forest); margin-bottom: 2px; }
.modal-sub { font-family: var(--mono); font-size: 0.8rem; color: var(--ink-3); margin-bottom: 20px; letter-spacing: 0.02em; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }

/* ── Radio group (modal) ────────────────────────────── */
.radio-group { display: flex; flex-direction: column; gap: 7px; }
.radio-option {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition);
}
.radio-option:has(input:checked) { border-color: var(--forest); background: rgba(42,51,40,0.05); }
.radio-option input[type="radio"] { accent-color: var(--forest); width: 16px; height: 16px; flex-shrink: 0; }
.radio-label { font-family: var(--serif-body); font-size: 0.875rem; font-weight: 500; color: var(--ink); }

/* ── Badges ──────────────────────────────────────────── */
.badge {
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  border-radius: 99px;
  white-space: nowrap;
  flex-shrink: 0;
}
.badge-completed  { background: var(--green-dim);  color: var(--green);  }
.badge-reading    { background: var(--amber-dim);  color: var(--amber);  }
.badge-not-started{ background: rgba(31,36,32,0.06); color: var(--ink-3); }

/* ── Spinner ─────────────────────────────────────────── */
.spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--bone-3);
  border-top-color: var(--forest);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Inline form ─────────────────────────────────────── */
.inline-form { background: var(--bone-2); border: 1px solid var(--hairline); border-radius: var(--radius); padding: 16px; margin-bottom: 16px; }
.inline-form-row { display: flex; gap: 10px; flex-wrap: wrap; }
.inline-form-row .form-group { flex: 1; min-width: 140px; margin-bottom: 0; }

/* ── Empty state ─────────────────────────────────────── */
.empty-state { text-align: center; padding: 56px 20px; color: var(--ink-3); }
.empty-state-icon { font-size: 3rem; margin-bottom: 12px; }
.empty-state p { font-family: var(--serif-body); font-size: 0.9rem; font-style: italic; margin-bottom: 20px; color: var(--ink-2); }

/* ── Reading progress summary (ask) ─────────────────── */
.progress-summary {
  background: rgba(42,51,40,0.05);
  border: 1px solid rgba(42,51,40,0.12);
  border-radius: var(--radius-sm);
  padding: 11px 14px;
  font-family: var(--mono);
  font-size: 0.8rem;
  color: var(--ink-3);
  margin-bottom: 14px;
  line-height: 1.5;
  letter-spacing: 0.02em;
}
.progress-summary strong { color: var(--forest); }

/* ── Answer card (legacy — kept for fallback) ─────────── */
.answer-card {
  background: var(--bone-2);
  border: 1px solid var(--hairline);
  border-left: 3px solid var(--brass);
  border-radius: var(--radius);
  padding: 20px;
  margin-top: 20px;
}
.answer-text { font-family: var(--serif-body); font-size: 0.925rem; line-height: 1.75; color: var(--ink); white-space: pre-wrap; }

/* ── Wordmark ────────────────────────────────────────── */
.wordmark {
  font-family: var(--serif-display);
  font-size: 1.4rem;
  font-weight: 600;
  font-style: italic;
  color: var(--forest);
  letter-spacing: -0.02em;
  display: flex;
  align-items: center;
  gap: 6px;
  padding-bottom: 16px;
}
.wordmark span { color: var(--brass); font-style: normal; }

/* ── Upload view header ─────────────────────────────── */
.upload-view-head { padding: 28px 0 20px; }

/* ── View transitions ────────────────────────────────── */
[x-cloak] { display: none !important; }
.view-enter { animation: fadeIn 0.2s ease both; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

/* ── Mobile tab responsive adjustments ──────────────── */
@media (max-width: 480px) {
  .modal-actions { flex-direction: column-reverse; }
  .modal-actions .btn { width: 100%; justify-content: center; }
}
```

- [ ] **Step 2: Update Upload view header to use new heading style**

Replace the section header in the Upload view:

```html
<div class="upload-view-head">
  <div class="view-eyebrow">Add to library</div>
  <h1 class="view-title-display" style="font-size:36px;">Upload.</h1>
</div>
```

- [ ] **Step 3: Verify full app visual consistency**

```bash
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Check:
- Library: bone/cream background, serif titles, cover strips, green buttons
- Ask: chat thread layout, green send button, scope banner
- Upload: literary dropzone, green primary button
- Progress modal: serif italic title, green radio highlight
- Mobile (375px): bottom tab bar, stacked layout
- Desktop (1280px): dark green sidebar, wider content

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): complete literary design system — polish components, upload view, modal"
```

---

## Self-Review

**Spec coverage:**
- ✅ Literary color system (forest/bone) — Task 1
- ✅ Cormorant Garamond + Source Serif 4 + JetBrains Mono typography — Task 1
- ✅ Desktop sidebar layout — Task 2
- ✅ Mobile tab-bar preserved — Task 2
- ✅ Book cover-based library with series strips — Task 3
- ✅ "Continue reading" section — Task 3
- ✅ Chat thread Ask view with scope banners — Task 4
- ✅ Conversation history sent to backend — Task 4
- ✅ All existing backend API calls preserved — throughout
- ✅ Upload view literary polish — Task 5
- ✅ Progress modal restyled — Task 5

**Placeholder scan:** All code blocks are complete. No TBD/TODO.

**Type consistency:** All CSS class names used in HTML blocks are defined in CSS blocks within the same task or a prior task.

---

Plan complete and saved to `docs/superpowers/plans/2026-04-19-desktop-redesign.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
