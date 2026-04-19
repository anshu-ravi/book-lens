import sys

with open("src/static/index.html", "r") as f:
    html = f.read()

# 1. Ask Mode & Citations
html = html.replace(
    "ask: {\n      seriesId: '',",
    "ask: {\n      seriesId: '',\n      mode: 'default',"
)

composer_html = """        <div class="composer-row">"""
new_composer_html = """        <div class="composer-series-row" style="margin-top: 6px;">
          <span class="composer-series-label">Mode:</span>
          <select x-model="ask.mode" style="font-family:var(--mono);font-size:11px;padding:3px 24px 3px 6px;background:var(--bone-2);border:1px solid var(--hairline);border-radius:4px;color:var(--ink);outline:none;appearance:none;">
            <option value="default">Default</option>
            <option value="theory">Theory</option>
            <option value="recap">Recap</option>
          </select>
        </div>
        <div class="composer-row">"""
html = html.replace(composer_html, new_composer_html, 1)

html = html.replace(
    "conversation_history: history,\n          }),",
    "conversation_history: history,\n            mode: this.ask.mode,\n          }),"
)

# Render citations into spans
html = html.replace(
    "text: data.answer,",
    "text: data.answer.replace(/\\[[cC]h\\.? (.*?)\\]/g, '<span class=\"badge badge-completed\" style=\"cursor:pointer; font-size:9px; padding:2px 4px; margin:0 2px;\">[Ch. $1]</span>'),"
)

# 2. Proactive Prompts
# In saveProgress, after updating reading
html = html.replace(
    "this.updateReadingSummary();",
    "this.updateReadingSummary();\n        if (this.modal.status === 'reading' && (!this.modal.book.current_chapter_index || this.modal.chapterIndex > this.modal.book.current_chapter_index)) {\n          this.fetchProactivePrompt(this.modal.series.id, this.modal.book.index, this.modal.chapterIndex);\n        }"
)

# Add fetchProactivePrompt and state
html = html.replace(
    "ask: {",
    "proactivePrompt: null,\n\n    async fetchProactivePrompt(seriesId, bookIndex, chapterIndex) {\n      try {\n        const res = await fetch('/query/prompts', {\n          method: 'POST',\n          headers: {'Content-Type': 'application/json'},\n          body: JSON.stringify({ series_id: seriesId, book_index: bookIndex, chapter_index: chapterIndex })\n        });\n        if (res.ok) {\n           const data = await res.json();\n           this.proactivePrompt = data.question;\n        }\n      } catch (e) {}\n    },\n\n    ask: {"
)

library_view_marker = "<!-- ═══════════════════ ASK VIEW ═══════════════════════ -->"
toast_ui = """    <!-- Proactive Toast -->
    <div x-show="proactivePrompt" x-transition style="position:fixed; bottom:80px; right:20px; max-width:300px; background:var(--forest); color:var(--bone); padding:16px; border-radius:var(--radius); box-shadow:var(--shadow); z-index:50;">
      <div style="font-family:var(--mono); font-size:10px; color:var(--brass); margin-bottom:4px; text-transform:uppercase;">Companion Idea</div>
      <div style="font-size:13px; margin-bottom:12px;" x-text="proactivePrompt"></div>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-sm" style="background:var(--bone-2); color:var(--ink);" @click="switchView('ask'); ask.question = proactivePrompt; proactivePrompt = null;">Ask</button>
        <button class="btn-ghost btn-sm" style="color:var(--bone-2); border-color:var(--bone-3);" @click="proactivePrompt = null">Dismiss</button>
      </div>
    </div>

"""
html = html.replace(library_view_marker, toast_ui + library_view_marker)

# 3. Lore Compendium
tab_mobile_html = """<button class="tab" :class="{ active: view === 'ask' }" @click="switchView('ask')">"""
comp_tab_html = """      <button class="tab" :class="{ active: view === 'compendium' }" @click="switchView('compendium'); loadCompendium();">
        <svg viewBox="0 0 20 20" fill="none"><path d="M4 4h12M4 10h12M4 16h6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
        Lore
        <div class="tab-dot"></div>
      </button>
"""
html = html.replace(tab_mobile_html, comp_tab_html + tab_mobile_html, 1)

html = html.replace(
    "proactivePrompt: null,",
    "compendium: { characters: [], seriesId: '' },\n    loadingCompendium: false,\n    proactivePrompt: null,"
)
comp_method = """    async loadCompendium() {
      if (!this.library?.series?.length) return;
      const reading = this.currentlyReading();
      const seriesId = reading.length > 0 ? reading[0]._series.id : this.library.series[0].id;
      if (this.compendium.seriesId === seriesId) return;
      
      this.loadingCompendium = true;
      try {
        const res = await fetch(`/library/series/${seriesId}/knowledge`);
        if (res.ok) {
           const data = await res.json();
           this.compendium.characters = data.characters || [];
           this.compendium.seriesId = seriesId;
        }
      } catch (e) {} finally {
        this.loadingCompendium = false;
      }
    },
"""
html = html.replace("async init() {", comp_method + "\n    async init() {")

comp_view_ui = """    <!-- ═══════════════════ COMPENDIUM VIEW ═══════════════════════ -->
    <div x-show="view === 'compendium'" class="view-enter" style="padding:20px 0;">
      <header class="ask-view-header" style="margin-bottom:20px;">
        <div class="view-eyebrow">Lore Compendium</div>
        <h1 class="view-title-display" style="font-size:32px;">Characters & Lore</h1>
      </header>
      
      <div x-show="loadingCompendium" class="empty-state">
        <span class="spinner"></span>
        <p>Loading compendium...</p>
      </div>

      <div x-show="!loadingCompendium && compendium.characters.length === 0" class="empty-state">
        <p>No characters discovered yet. Extract knowledge for a book first.</p>
      </div>
      
      <div x-show="!loadingCompendium && compendium.characters.length > 0" style="display:flex; flex-direction:column; gap:16px;">
        <template x-for="char in compendium.characters" :key="char.name">
          <div class="card">
            <div class="card-title" x-text="char.name"></div>
            <div class="card-sub" x-text="char.archetype" style="margin-bottom:8px; color:var(--moss);"></div>
            <p style="font-size:13px; color:var(--ink-2);" x-text="char.traits.join(', ')"></p>
          </div>
        </template>
      </div>
    </div>

"""
html = html.replace(library_view_marker, comp_view_ui + library_view_marker)

with open("src/static/index.html", "w") as f:
    f.write(html)
