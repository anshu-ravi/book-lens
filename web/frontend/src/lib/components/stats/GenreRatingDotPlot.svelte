<script lang="ts">
	import type { GoodreadsStatsGenreRating } from '$lib/types';
	import ChartTooltip from './ChartTooltip.svelte';
	import { ellipsize } from './chartUtils';

	let { data }: { data: GoodreadsStatsGenreRating[] } = $props();

	const ROW_H = 30;
	const ML = 130;
	const MR = 20;
	const MT = 4;
	const MB = 20;
	const MIN_R = 1;
	const MAX_R = 5;

	let w = $state(0);
	let hovered = $state<number | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	let n = $derived(data.length);
	let H = $derived(MT + MB + n * ROW_H);
	let axisW = $derived(Math.max(0, w - ML - MR));

	function scaleX(rating: number): number {
		return ML + ((rating - MIN_R) / (MAX_R - MIN_R)) * axisW;
	}

	let ticks = $derived([1, 2, 3, 4, 5]);

	function setHovered(i: number, evt?: PointerEvent) {
		hovered = i;
		if (evt) {
			const rect = (evt.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
			if (rect) pointer = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
		} else {
			const d = data[i];
			if (d) pointer = { x: scaleX(d.avg_rating), y: MT + i * ROW_H + ROW_H / 2 };
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
		return `genre-rating-opt-${i}`;
	}
</script>

<div
	class="plot"
	bind:clientWidth={w}
	tabindex="0"
	role="listbox"
	aria-label="Average rating by genre, on a scale of 1 to 5"
	aria-activedescendant={hovered !== null ? optionId(hovered) : undefined}
	onkeydown={onKeydown}
>
	{#if w > 0}
		{#if n === 0}
			<p class="empty-note">
				Genres haven't been imported yet — run enrichment to see ratings by genre.
			</p>
		{:else}
			<svg width={w} height={H} viewBox="0 0 {w} {H}" role="presentation">
				{#each ticks as t (t)}
					<line x1={scaleX(t)} y1={MT} x2={scaleX(t)} y2={H - MB} class="gridline" />
					<text x={scaleX(t)} y={H - MB + 16} class="axis-label">{t}</text>
				{/each}

				{#each data as g, i (g.genre)}
					{@const rowY = MT + i * ROW_H}
					{@const cx = scaleX(g.avg_rating)}
					{@const cy = rowY + ROW_H / 2}
					{@const isHovered = hovered === i}
					{@const isDimmed = hovered !== null && !isHovered}
					<text x={ML - 10} y={cy + 4} class="row-label">
						{ellipsize(g.genre, 20)}<title>{g.genre}</title>
					</text>
					<line x1={ML} y1={cy} x2={w - MR} y2={cy} class="row-rule" />
					<circle cx={cx} cy={cy} r="6" class="dot-ring" opacity={isDimmed ? 0.45 : 1} />
					<circle cx={cx} cy={cy} r="4" class="dot" opacity={isDimmed ? 0.45 : 1} />
					<rect
						x="0"
						y={rowY}
						width={w}
						height={ROW_H}
						class="hit"
						role="option"
						id={optionId(i)}
						aria-selected={hovered === i}
						aria-label="{g.genre}: average rating {g.avg_rating.toFixed(1)} across {g.books} books"
						onpointerenter={(e) => setHovered(i, e)}
						onpointermove={(e) => setHovered(i, e)}
						onpointerleave={() => (hovered = null)}
					/>
				{/each}
			</svg>

			{#if hovered !== null && data[hovered]}
				<ChartTooltip x={pointer.x} y={pointer.y} containerWidth={w}>
					<strong>{data[hovered].genre}</strong><br />
					{data[hovered].avg_rating.toFixed(1)} avg · {data[hovered].books} book{data[hovered]
						.books === 1
						? ''
						: 's'}
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
	.row-rule {
		stroke: var(--ink-hairline);
		stroke-width: 1;
	}
	.gridline {
		stroke: var(--ink-hairline);
		stroke-width: 1;
	}
	.axis-label {
		font-family: var(--mono);
		font-variant-numeric: tabular-nums;
		font-size: 11px;
		fill: var(--bone-faint);
		text-anchor: middle;
	}
	.dot {
		fill: var(--brass);
		transition: opacity 0.1s ease;
	}
	.dot-ring {
		fill: var(--ink-surface);
		transition: opacity 0.1s ease;
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
