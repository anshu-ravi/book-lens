<script lang="ts">
	import type { GoodreadsStatsMonth, GoodreadsStatsMonthBook } from '$lib/types';
	import BookCover from '$lib/components/library/BookCover.svelte';
	import ChartTooltip from './ChartTooltip.svelte';
	import { formatDateLong } from '$lib/utils/format-date';
	import { monthIndex, monthFullLabel, MONTH_ABBR } from './chartUtils';

	let { data }: { data: GoodreadsStatsMonth[] } = $props();

	const TILE_W = 52;
	const TILE_H = 78;
	const TILE_GAP = 6;
	const COL_MIN = 56;
	const TOP_PAD = 12;
	const LABEL_H = 34;

	let containerW = $state(0);
	let stripEl: HTMLDivElement | undefined = $state();
	let scrollEl: HTMLDivElement | undefined = $state();
	let hovered = $state<number | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	let scrollLeft = $state(0);
	let scrollWidth = $state(0);
	let clientWidth = $state(0);

	function readScrollGeometry() {
		if (!scrollEl) return;
		scrollLeft = scrollEl.scrollLeft;
		scrollWidth = scrollEl.scrollWidth;
		clientWidth = scrollEl.clientWidth;
	}

	let canScroll = $derived(scrollWidth > clientWidth + 1);
	let showLeftFade = $derived(canScroll && scrollLeft > 1);
	let showRightFade = $derived(canScroll && scrollLeft < scrollWidth - clientWidth - 1);

	let n = $derived(data.length);
	let maxCount = $derived(Math.max(0, ...data.map((d) => d.count)));
	let hasAny = $derived(maxCount > 0);

	let colWidth = $derived(n > 0 && containerW > 0 ? Math.max(COL_MIN, containerW / n) : COL_MIN);
	let totalWidth = $derived(colWidth * n);

	// Re-measure whenever the strip's own content width or the container's
	// width changes -- covers both a data swap (year filter) and a window
	// resize, either of which can flip whether the strip overflows at all.
	$effect(() => {
		void totalWidth;
		void containerW;
		readScrollGeometry();
	});

	$effect(() => {
		window.addEventListener('resize', readScrollGeometry);
		return () => window.removeEventListener('resize', readScrollGeometry);
	});

	let stackAreaH = $derived(
		maxCount > 0 ? maxCount * TILE_H + (maxCount - 1) * TILE_GAP : TILE_H,
	);
	let baselineY = $derived(TOP_PAD + stackAreaH);
	let totalHeight = $derived(baselineY + LABEL_H);

	function tileTop(bookIdx: number): number {
		return baselineY - (bookIdx + 1) * TILE_H - bookIdx * TILE_GAP;
	}

	let flat = $derived.by(() => {
		const out: { mi: number; bi: number; book: GoodreadsStatsMonthBook }[] = [];
		data.forEach((m, mi) => m.books.forEach((book, bi) => out.push({ mi, bi, book })));
		return out;
	});

	function optionId(i: number): string {
		return `cover-opt-${flat[i]?.book.goodreads_book_id ?? i}`;
	}

	function selectTile(i: number, evt?: PointerEvent) {
		hovered = i;
		const f = flat[i];
		if (!f) return;
		if (evt && stripEl) {
			const rect = stripEl.getBoundingClientRect();
			pointer = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
		} else {
			pointer = { x: f.mi * colWidth + colWidth / 2, y: tileTop(f.bi) };
		}
	}

	function onKeydown(evt: KeyboardEvent) {
		if (flat.length === 0) return;
		if (evt.key === 'ArrowRight' || evt.key === 'ArrowDown') {
			evt.preventDefault();
			selectTile(Math.min(flat.length - 1, (hovered ?? -1) + 1));
		} else if (evt.key === 'ArrowLeft' || evt.key === 'ArrowUp') {
			evt.preventDefault();
			selectTile(Math.max(0, (hovered ?? flat.length) - 1));
		} else if (evt.key === 'Escape') {
			hovered = null;
			return;
		} else {
			return;
		}
		if (hovered !== null) {
			document
				.getElementById(optionId(hovered))
				?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
		}
	}

	let stripLabel = $derived(
		n === 0 ? 'Books read by month' : `Books read by month, ${data[0].month} through ${data[n - 1].month}`,
	);

	let hoveredStars = $derived.by(() => {
		const rating = hovered !== null ? flat[hovered]?.book.rating : null;
		return rating ? Array.from({ length: 5 }, (_, i) => i < rating) : null;
	});
</script>

<div class="cover-strip">
	{#if !hasAny}
		<p class="empty-note">No dated finishes in this range.</p>
	{:else}
		<div
			class="strip-scroll"
			bind:this={scrollEl}
			bind:clientWidth={containerW}
			tabindex="0"
			role="listbox"
			aria-label={stripLabel}
			aria-activedescendant={hovered !== null ? optionId(hovered) : undefined}
			onkeydown={onKeydown}
			onscroll={readScrollGeometry}
		>
			<div class="strip" bind:this={stripEl} style="width:{totalWidth}px; height:{totalHeight}px;">
				<div class="baseline" style="top:{baselineY}px; width:{totalWidth}px;"></div>

				{#each data as m, mi (m.month)}
					{@const colX = mi * colWidth}
					<div class="month-label small-caps" style="left:{colX}px; width:{colWidth}px; top:{baselineY + 8}px;">
						{MONTH_ABBR[monthIndex(m.month)]}
					</div>
					{#if mi === 0 || monthIndex(m.month) === 0}
						<div class="year-label small-caps" style="left:{colX}px; width:{colWidth}px; top:{baselineY + 20}px;">
							{m.month.split('-')[0]}
						</div>
					{/if}
				{/each}

				{#each flat as f, i (f.book.goodreads_book_id)}
					{@const tileX = f.mi * colWidth + (colWidth - TILE_W) / 2}
					{@const tileY = tileTop(f.bi)}
					{@const isHovered = hovered === i}
					{@const isDimmed = hovered !== null && !isHovered}
					<div
						class="tile"
						class:lifted={isHovered}
						style="left:{tileX}px; top:{tileY}px; width:{TILE_W}px; height:{TILE_H}px; opacity:{isDimmed
							? 0.45
							: 1};"
						role="option"
						id={optionId(i)}
						aria-selected={isHovered}
						aria-label="{f.book.title}, {monthFullLabel(data[f.mi].month)}"
						onpointerenter={(e) => selectTile(i, e)}
						onpointermove={(e) => selectTile(i, e)}
						onpointerleave={() => (hovered = null)}
					>
						<BookCover
							fill
							title={f.book.title}
							author={f.book.author ?? ''}
							seriesId={f.book.series ?? f.book.goodreads_book_id}
							positionInSeries={f.book.series_number ?? undefined}
							coverUrl={f.book.cover}
						/>
					</div>
				{/each}
			</div>
		</div>
		{#if showLeftFade}<div class="edge-fade edge-fade-left" aria-hidden="true"></div>{/if}
		{#if showRightFade}<div class="edge-fade edge-fade-right" aria-hidden="true"></div>{/if}

		{#if hovered !== null && flat[hovered]}
			{@const f = flat[hovered]}
			<ChartTooltip x={pointer.x} y={pointer.y} containerWidth={containerW}>
				<div class="tile-tooltip">
					<strong>{f.book.title}</strong><br />
					{#if f.book.author}{f.book.author}<br />{/if}
					{#if f.book.series}
						{f.book.series}{f.book.series_number !== null ? ` · Vol. ${f.book.series_number}` : ''}<br />
					{/if}
					{#if f.book.pages !== null}{f.book.pages} pages<br />{/if}
					{#if hoveredStars}
						<span class="stars" aria-hidden="true">
							{#each hoveredStars as filled}<span class="star" class:filled>★</span>{/each}
						</span>
						<br />
					{/if}
					{#if f.book.date_read}{formatDateLong(f.book.date_read)}{/if}
				</div>
			</ChartTooltip>
		{/if}
	{/if}
</div>

<style>
	.cover-strip {
		position: relative;
	}
	.strip-scroll {
		overflow-x: auto;
		overflow-y: hidden;
	}
	.strip-scroll:focus-visible {
		outline: 1px solid var(--brass);
		outline-offset: 2px;
	}
	/* The card's own surface colour eating the strip's edge, not a grey
	   smear -- so the fade must use the same token ChartCard paints its
	   background with, not a hard-coded colour. */
	.edge-fade {
		position: absolute;
		top: 0;
		bottom: 0;
		width: var(--sp-12);
		pointer-events: none;
		z-index: 3;
	}
	.edge-fade-left {
		left: 0;
		background: linear-gradient(to right, var(--ink-surface), transparent);
	}
	.edge-fade-right {
		right: 0;
		background: linear-gradient(to left, var(--ink-surface), transparent);
	}
	.strip {
		position: relative;
	}
	.baseline {
		position: absolute;
		left: 0;
		height: 1px;
		background: var(--ink-hairline);
	}
	.month-label {
		position: absolute;
		text-align: center;
		color: var(--bone-faint);
	}
	.year-label {
		position: absolute;
		text-align: center;
		color: var(--brass-text);
	}
	.tile {
		position: absolute;
		border: var(--hairline);
		border-radius: var(--r-cover);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
		cursor: pointer;
		transition: transform 0.12s ease, opacity 0.1s ease;
	}
	:global(:root[data-theme='light']) .tile {
		box-shadow: 0 4px 14px rgba(31, 36, 32, 0.18);
	}
	.tile.lifted {
		transform: translateY(-6px);
		z-index: 2;
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
	.tile-tooltip {
		white-space: normal;
		max-width: 200px;
	}
	.stars {
		display: inline-flex;
		gap: 1px;
	}
	.star {
		color: var(--brass-dim);
	}
	.star.filled {
		color: var(--brass);
	}
</style>
