<script lang="ts">
	import type { UnifiedEntry, UnifiedGroup, UnifiedShelf } from '$lib/types';

	const INITIAL_LIMIT = 12;
	const MIN_PAGES = 96;
	const MAX_PAGES = 1088;
	const DEFAULT_PAGES = 466;
	const MIN_HEIGHT = 150;
	const MAX_HEIGHT = 166;

	let { shelf, onopen }: { shelf: UnifiedShelf; onopen: (entry: UnifiedEntry) => void } = $props();

	let failedCovers = $state(new Set<string>());

	function coverKey(entry: UnifiedEntry, gi: number, bi: number): string {
		return entry.book_id ?? entry.goodreads_book_id ?? `${gi}-${bi}`;
	}

	/** Groups stay intact -- the cap trims whole volumes-of-a-series together, never mid-series. */
	function limitGroups(groups: UnifiedGroup[], max: number): UnifiedGroup[] {
		const out: UnifiedGroup[] = [];
		let count = 0;
		for (const g of groups) {
			if (count > 0 && count >= max) break;
			out.push(g);
			count += g.books.length;
		}
		return out;
	}

	const visibleGroups = $derived(limitGroups(shelf.groups, INITIAL_LIMIT));

	function bookHeight(numPages: number | null): number {
		const pages = Math.min(MAX_PAGES, Math.max(MIN_PAGES, numPages ?? DEFAULT_PAGES));
		const t = (pages - MIN_PAGES) / (MAX_PAGES - MIN_PAGES);
		return Math.round(MIN_HEIGHT + t * (MAX_HEIGHT - MIN_HEIGHT));
	}
</script>

<section class="row">
	<div class="row-hd">
		<h2>{shelf.label}</h2>
		<span class="ct">{shelf.count}</span>
		<a href="/library?shelf={shelf.shelf}" class="full small-caps">See all &rarr;</a>
	</div>
	<div class="alcove">
		<div class="bks">
			{#each visibleGroups as group, gi (group.series ?? `standalone-${gi}`)}
				<div class="grp" class:multi={group.books.length > 1}>
					{#each group.books as book, bi (coverKey(book, gi, bi))}
						{@const key = coverKey(book, gi, bi)}
						<button
							type="button"
							class="bk"
							style="--bh:{bookHeight(book.num_pages)}px"
							title="{book.display_title} - {book.author}"
							onclick={() => onopen(book)}
						>
							<span class="bk-c">
								{#if book.cover && !failedCovers.has(key)}
									<img
										src={book.cover}
										alt=""
										loading="lazy"
										onerror={() => (failedCovers = new Set([...failedCovers, key]))}
									/>
								{:else}
									<span class="fb"></span>
								{/if}
								{#if group.books.length > 1 && book.series_number !== null}
									<span class="vol">{book.series_number}</span>
								{/if}
								{#if book.askable}
									<span class="ask" title="EPUB ingested"></span>
								{/if}
							</span>
						</button>
					{/each}
					{#if group.books.length > 1}
						<span class="tie"><i></i><em>{group.series}</em></span>
					{:else}
						<span class="tie"></span>
					{/if}
				</div>
			{/each}
		</div>
		<div class="ledge"></div>
	</div>
</section>

<style>
	.row {
		margin-bottom: var(--sp-12);
	}
	.row-hd {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		margin-bottom: var(--sp-4);
	}
	.row-hd h2 {
		font-family: var(--sans-caps);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		font-size: var(--fs-12);
		font-weight: 400;
		color: var(--bone);
		margin: 0;
	}
	.ct {
		font-family: var(--mono);
		font-size: var(--fs-12);
		color: var(--bone-faint);
	}
	:root[data-theme='light'] .ct {
		color: var(--bone-muted);
	}
	.full {
		margin-left: auto;
		font-family: var(--sans-caps);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		font-size: var(--fs-12);
		color: var(--brass-text);
		background: none;
		border: none;
		cursor: pointer;
		padding: 0;
		text-decoration: none;
	}
	.full:hover {
		text-decoration: underline;
	}
	.alcove {
		position: relative;
		background:
			linear-gradient(180deg, rgba(0, 0, 0, 0.34) 0%, rgba(0, 0, 0, 0) 38%),
			linear-gradient(180deg, transparent 62%, rgba(255, 255, 255, 0.035) 100%),
			var(--alcove);
		border: var(--hairline);
		border-radius: var(--r-shelf) var(--r-shelf) calc(var(--r-shelf) + 3px) calc(var(--r-shelf) + 3px);
		padding: var(--sp-6) var(--sp-6) 0;
		box-shadow: inset 0 9px 16px -10px rgba(0, 0, 0, 0.85), 0 14px 30px -16px rgba(0, 0, 0, 0.55);
		overflow: hidden;
	}
	:root[data-theme='light'] .alcove {
		background:
			linear-gradient(180deg, rgba(90, 72, 48, 0.1) 0%, rgba(90, 72, 48, 0) 38%),
			linear-gradient(180deg, transparent 62%, rgba(255, 255, 255, 0.55) 100%),
			var(--alcove);
		box-shadow: inset 0 8px 14px -10px rgba(90, 72, 48, 0.4), 0 12px 26px -16px rgba(90, 72, 48, 0.32);
	}
	.bks {
		display: flex;
		align-items: flex-end;
		gap: var(--sp-6);
		overflow-x: auto;
		scrollbar-width: none;
		-webkit-mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 56px), transparent 100%);
		mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 56px), transparent 100%);
	}
	.bks::-webkit-scrollbar {
		display: none;
	}
	.grp {
		display: flex;
		align-items: flex-end;
		gap: var(--sp-1);
		flex: 0 0 auto;
		position: relative;
		padding-bottom: 19px;
	}
	.bk {
		flex: 0 0 auto;
		display: flex;
		flex-direction: column;
		align-items: center;
		position: relative;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.bk::after {
		content: '';
		position: absolute;
		left: -5px;
		right: -5px;
		bottom: 15px;
		height: 8px;
		background: radial-gradient(ellipse at 50% 0%, rgba(0, 0, 0, 0.55), transparent 72%);
		opacity: 0.9;
		pointer-events: none;
	}
	:root[data-theme='light'] .bk::after {
		background: radial-gradient(ellipse at 50% 0%, rgba(90, 72, 48, 0.34), transparent 72%);
	}
	.bk-c {
		position: relative;
		display: block;
		width: 104px;
		height: var(--bh, 156px);
		border-radius: 1px var(--r-cover) var(--r-cover) 1px;
		overflow: hidden;
		background: var(--ink-surface);
		box-shadow: 0 10px 20px -6px rgba(0, 0, 0, 0.55), inset 2px 0 0 rgba(0, 0, 0, 0.22);
		transition: transform 0.18s ease;
	}
	:root[data-theme='light'] .bk-c {
		box-shadow: 0 10px 20px -8px rgba(90, 72, 48, 0.45), inset 2px 0 0 rgba(90, 72, 48, 0.16);
	}
	.bk:hover .bk-c {
		transform: translateY(-7px);
	}
	.bk-c img,
	.bk-c .fb {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.fb {
		background: var(--ink-surface);
	}
	.vol {
		position: absolute;
		top: 0;
		left: 0;
		background: var(--ink-bg);
		color: var(--bone-muted);
		border-right: var(--hairline);
		border-bottom: var(--hairline);
		font-family: var(--mono);
		font-size: var(--fs-12);
		padding: 1px 6px;
	}
	.ask {
		position: absolute;
		bottom: 6px;
		right: 6px;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--brass);
		box-shadow: 0 0 0 2px var(--alcove);
	}
	.tie {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 6px;
		height: 12px;
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}
	.grp.multi .tie i {
		flex: 1;
		height: 1px;
		background: var(--tie-line);
	}
	.grp.multi .tie em {
		font-style: normal;
		font-family: var(--sans-caps);
		font-size: var(--fs-12);
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--brass-text);
		white-space: nowrap;
		order: -1;
		transform: scale(0.9);
		transform-origin: left center;
	}
	:root[data-theme='light'] .grp.multi .tie em {
		font-weight: 600;
	}
	.ledge {
		height: 11px;
		margin: 0 calc(var(--sp-6) * -1);
		border-radius: 0 0 calc(var(--r-shelf) + 2px) calc(var(--r-shelf) + 2px);
		background: linear-gradient(180deg, var(--ledge-hi) 0 1px, var(--ledge) 1px 7px, var(--ledge-lip) 7px 100%);
		box-shadow: 0 9px 16px -7px rgba(0, 0, 0, 0.66);
	}
	:root[data-theme='light'] .ledge {
		box-shadow: 0 8px 14px -7px rgba(90, 72, 48, 0.4);
	}
	@media (max-width: 900px) {
		.bk-c {
			width: 84px;
		}
	}
</style>
