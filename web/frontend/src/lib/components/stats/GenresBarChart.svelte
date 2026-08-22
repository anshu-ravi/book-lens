<script lang="ts">
	import type { GoodreadsStatsGenre } from '$lib/types';
	import ChartTooltip from './ChartTooltip.svelte';
	import { hBarPath, ellipsize } from './chartUtils';

	let { data }: { data: GoodreadsStatsGenre[] } = $props();

	const ROW_H = 30;
	const ML = 130;
	// Wide enough for a 3-digit tabular-nums label at the tip of the longest bar.
	const MR = 40;
	const MT = 4;
	const MB = 4;

	let w = $state(0);
	let hovered = $state<number | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	let n = $derived(data.length);
	let H = $derived(MT + MB + n * ROW_H);
	let barMaxWidth = $derived(Math.max(0, w - ML - MR));
	let maxBooks = $derived(Math.max(1, ...data.map((d) => d.books)));

	let bars = $derived(
		data.map((d, i) => {
			const width = (d.books / maxBooks) * barMaxWidth;
			const y = MT + i * ROW_H;
			const thickness = Math.min(24, ROW_H - 10);
			return { x: ML, y: y + (ROW_H - thickness) / 2, width, thickness, rowY: y };
		}),
	);

	function setHovered(i: number, evt?: PointerEvent) {
		hovered = i;
		if (evt) {
			const rect = (evt.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
			if (rect) pointer = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
		} else {
			const b = bars[i];
			if (b) pointer = { x: b.x + b.width, y: b.rowY + ROW_H / 2 };
		}
	}

	function onKeydown(evt: KeyboardEvent) {
		if (n === 0) return;
		if (evt.key === 'ArrowRight' || evt.key === 'ArrowDown') {
			evt.preventDefault();
			setHovered(Math.min(n - 1, (hovered ?? -1) + 1));
		} else if (evt.key === 'ArrowLeft' || evt.key === 'ArrowUp') {
			evt.preventDefault();
			setHovered(Math.max(0, (hovered ?? n) - 1));
		} else if (evt.key === 'Escape') {
			hovered = null;
		}
	}

	function optionId(i: number): string {
		return `genres-opt-${i}`;
	}
</script>

<div
	class="plot"
	bind:clientWidth={w}
	tabindex="0"
	role="listbox"
	aria-label="Books read by genre, by number of books"
	aria-activedescendant={hovered !== null ? optionId(hovered) : undefined}
	onkeydown={onKeydown}
>
	{#if w > 0}
		{#if n === 0}
			<p class="empty-note">Genres haven't been imported yet — run enrichment to see them here.</p>
		{:else}
			<svg width={w} height={H} viewBox="0 0 {w} {H}" role="presentation">
				{#each data as g, i (g.genre)}
					{@const bar = bars[i]}
					{@const isHovered = hovered === i}
					{@const isDimmed = hovered !== null && !isHovered}
					<text x={ML - 10} y={bar.rowY + ROW_H / 2 + 4} class="row-label">
						{ellipsize(g.genre, 20)}<title>{g.genre}</title>
					</text>
					<path d={hBarPath(bar.x, bar.y, bar.width, bar.thickness)} class="bar" opacity={isDimmed ? 0.45 : 1} />
					<text x={bar.x + bar.width + 8} y={bar.rowY + ROW_H / 2 + 4} class="value-label">
						{g.books}
					</text>
					<rect
						x="0"
						y={bar.rowY}
						width={w}
						height={ROW_H}
						class="hit"
						role="option"
						id={optionId(i)}
						aria-selected={hovered === i}
						aria-label="{g.genre}: {g.books} books"
						onpointerenter={(e) => setHovered(i, e)}
						onpointermove={(e) => setHovered(i, e)}
						onpointerleave={() => (hovered = null)}
					/>
				{/each}
			</svg>

			{#if hovered !== null && data[hovered]}
				<ChartTooltip x={pointer.x} y={pointer.y} containerWidth={w}>
					<strong>{data[hovered].genre}</strong><br />
					{data[hovered].books} book{data[hovered].books === 1 ? '' : 's'}
				</ChartTooltip>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.plot {
		position: relative;
		width: 100%;
	}
	.plot:focus-visible {
		outline: 1px solid var(--brass);
		outline-offset: 2px;
	}
	svg {
		display: block;
	}
	.row-label {
		font-family: var(--serif-body);
		font-size: 12px;
		fill: var(--bone-muted);
		text-anchor: end;
	}
	.bar {
		fill: var(--brass);
		transition: opacity 0.1s ease;
	}
	.value-label {
		font-family: var(--mono);
		font-variant-numeric: tabular-nums;
		font-size: 11px;
		fill: var(--bone-faint);
	}
	.hit {
		fill: transparent;
		cursor: pointer;
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
</style>
