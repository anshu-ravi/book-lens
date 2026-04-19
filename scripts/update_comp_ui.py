import sys

with open("src/static/index.html", "r") as f:
    html = f.read()

comp_header_old = """      <header class="ask-view-header" style="margin-bottom:20px;">
        <div class="view-eyebrow">Lore Compendium</div>
        <h1 class="view-title-display" style="font-size:32px;">Characters & Lore</h1>
      </header>"""

comp_header_new = """      <header class="ask-view-header" style="margin-bottom:20px;">
        <div class="view-eyebrow">Lore Compendium</div>
        <h1 class="view-title-display" style="font-size:32px;">Characters & Lore</h1>
        <div class="composer-series-row" style="margin-top: 12px; gap: 8px;">
          <select x-model="compendium.seriesId" @change="loadCompendium()"
            style="font-family:var(--mono);font-size:11px;padding:5px 32px 5px 10px;background:var(--bone-2);border:1px solid var(--hairline);border-radius:4px;color:var(--ink);outline:none;appearance:none;background-image:url(&quot;data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a8864a' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E&quot;);background-repeat:no-repeat;background-position:right 10px center;">
            <option value="" disabled>Select a series...</option>
            <template x-for="s in (library?.series ?? [])" :key="s.id">
              <option :value="s.id" x-text="s.name"></option>
            </template>
          </select>
          <button class="btn btn-sm" style="background:var(--bone-2); color:var(--ink);" @click="syncLore()" :disabled="compendium.syncing || !compendium.seriesId">
            <span x-show="compendium.syncing" class="spinner" style="width:12px;height:12px;"></span>
            <span x-text="compendium.syncing ? 'Extracting Lore...' : 'Sync Lore'"></span>
          </button>
        </div>
      </header>"""

html = html.replace(comp_header_old, comp_header_new)

state_old = "compendium: { characters: [], seriesId: '' },"
state_new = "compendium: { characters: [], seriesId: '', syncing: false },"
html = html.replace(state_old, state_new)

sync_logic = """
    async syncLore() {
      if (!this.compendium.seriesId || !this.library?.series) return;
      const series = this.library.series.find(s => s.id === this.compendium.seriesId);
      if (!series || !series.books.length) return;
      
      this.compendium.syncing = true;
      try {
        for (const book of series.books) {
          if (book.status === 'not_started') continue;
          
          await fetch(`/library/series/${series.id}/books/${book.index}/extract`, {
            method: 'POST'
          });
        }
        await this.loadCompendium(true);
      } catch (e) {
        console.error("Sync failed", e);
      } finally {
        this.compendium.syncing = false;
      }
    },

    currentlyReading() {"""
html = html.replace("    currentlyReading() {", sync_logic)

load_comp_old = """    async loadCompendium() {
      if (!this.library?.series?.length) return;
      const reading = this.currentlyReading();
      const seriesId = reading.length > 0 ? reading[0]._series.id : this.library.series[0].id;
      if (this.compendium.seriesId === seriesId) return;"""

load_comp_new = """    async loadCompendium(force = false) {
      if (!force && this.compendium.seriesId && this.compendium.characters.length > 0) return;
      
      if (!this.library?.series?.length) return;
      const reading = this.currentlyReading();
      const defaultSeriesId = reading.length > 0 ? reading[0]._series.id : this.library.series[0].id;
      const seriesId = this.compendium.seriesId || defaultSeriesId;
      if (!force && this.compendium.seriesId === seriesId) return;"""

html = html.replace(load_comp_old, load_comp_new)

with open("src/static/index.html", "w") as f:
    f.write(html)
