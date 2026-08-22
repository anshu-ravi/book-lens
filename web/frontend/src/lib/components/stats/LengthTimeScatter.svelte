<script lang="ts">
	import type { GoodreadsStatsDurations } from '$lib/types';
	import ChartTooltip from './ChartTooltip.svelte';

	let { durations }: { durations: GoodreadsStatsDurations } = $props();

	const H = 300;
	const ML = 46;
	const MR = 16;
	const MT = 12;
	const MB = 34;

	let w = $state(0);
	let hoveredI = $state<number | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	let points0 = $derived((durations.books ?? []).filter((d) => d.pages > 0));
	let n = $derived(points0.length);

	let innerW = $derived(Math.max(0, w - ML - MR));
	let innerH = H - MT - MB;
	let maxPages = $derived(Math.max(1, ...points0.map((d) => d.pages)));
	let minPages = $derived(Math.min(0, ...points0.map((d) => d.pages)));
	let maxDays = $derived(Math.max(1, ...points0.map((d) => d.days)));
	let pagesRange = $derived(Math.max(1, maxPages - minPages));

	function scaleX(pages: number): number {
		return ML + ((pages - minPages) / pagesRange) * innerW;
	}
	function scaleY(days: number): number {
		return MT + innerH - (days / maxDays) * innerH;
	}

	let points = $derived(
		points0.map((d) => ({
			x: scaleX(d.pages),
			y: scaleY(d.days),
			title: d.title,
			pages: d.pages,
			days: d.days,
		})),
	);

	let xTicks = $derived([0, 0.5, 1].map((f) => Math.round(minPages + f * pagesRange)));
	let yTicks = $derived([0, 0.5, 1].map((f) => Math.round(f * maxDays)));

	function nearestIndex(px: number, py: number): number | null {
		if (points.length === 0) return null;
		let best = 0;
		let bestDist = Infinity;
		for (let i = 0; i < points.length; i++) {
			const dx = points[i].x - px;
			const dy = points[i].y - py;
			const dist = dx * dx + dy * dy;
			if (dist < bestDist) {
				bestDist = dist;
				best = i;
			}
		}
		return best;
	}

	function onPointerMove(evt: PointerEvent) {
		const rect = (evt.currentTarget as SVGElement).getBoundingClientRect();
		const px = evt.clientX - rect.left;
		const py = evt.clientY - rect.top;
		pointer = { x: px, y: py };
		hoveredI = nearestIndex(px, py);
	}

	let medianDays = $derived.by(() => {
		if (n === 0) return 0;
		const sorted = [...points0.map((d) => d.days)].sort((a, b) => a - b);
		const mid = Math.floor(sorted.length / 2);
		return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
	});

	let plotLabel = $derived(
		n === 0
			? 'Days to finish plotted against book length, one mark per book'
			: `Days to finish plotted against book length, one mark per book. ${n} book${n === 1 ? '' : 's'} plotted, median ${medianDays} day${medianDays === 1 ? '' : 's'} to finish.`,
	);
</script>

<div class="plot" bind:clientWidth={w} role="img" aria-label={plotLabel}>
	{#if w > 0}
		{#if n === 0}
			<p class="empty-note">No books with both a page count and a finish time yet.</p>
		{:else}
			<svg
				width={w}
				height={H}
				viewBox="0 0 {w} {H}"
				role="presentation"
				onpointermove={onPointerMove}
				onpointerleave={() => (hoveredI = null)}
			>
				{#each yTicks as tick (tick)}
					{@const y = scaleY(tick)}
					<line x1={ML} y1={y} x2={w - MR} y2={y} class="gridline" />
					<text x={ML - 8} y={y + 4} class="axis-label left">{tick}</text>
				{/each}

				{#each xTicks as tick (tick)}
					<text x={scaleX(tick)} y={H - MB + 16} class="axis-label bottom">{tick}</text>
				{/each}

				<text x={ML + innerW / 2} y={H - 6} class="axis-title">Pages</text>
				<text x={-(MT + innerH / 2)} y={12} class="axis-title" transform="rotate(-90)">Days</text>

				{#each points as p, i (p.title + i)}
					{@const isDimmed = hoveredI !== null && hoveredI !== i}
					<circle cx={p.x} cy={p.y} r="6" class="mark-ring" opacity={isDimmed ? 0.35 : 1} />
					<circle cx={p.x} cy={p.y} r="4" class="mark" opacity={isDimmed ? 0.35 : 1} />
				{/each}
			</svg>

			{#if hoveredI !== null && points[hoveredI]}
				<ChartTooltip x={pointer.x} y={pointer.y} containerWidth={w}>
					<strong>{points[hoveredI].title}</strong><br />
					{points[hoveredI].pages.toLocaleString()} pages · {points[hoveredI].days} day{points[
						hoveredI
					].days === 1
						? ''
						: 's'}
				</ChartTooltip>
			{/if}
		{/if}
	{/if}
</div>

{#if durations.fastest || durations.slowest}
	<p class="footnote">
		{#if durations.fastest}Fastest: <strong>{durations.fastest.title}</strong>, {durations.fastest
				.days} days.{/if}
		{#if durations.slowest}
			<br />Slowest: <strong>{durations.slowest.title}</strong>, {durations.slowest.days} days.
		{/if}
	</p>
{/if}

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
	.gridline {
		stroke: var(--ink-hairline);
		stroke-width: 1;
	}
	.axis-label {
		font-family: var(--mono);
		font-variant-numeric: tabular-nums;
		font-size: 11px;
		fill: var(--bone-faint);
	}
	.axis-label.left {
		text-anchor: end;
	}
	.axis-label.bottom {
		text-anchor: middle;
	}
	.axis-title {
		font-family: var(--sans-caps);
		font-size: 11px;
		letter-spacing: var(--tracking-caps);
		text-transform: uppercase;
		fill: var(--bone-muted);
		text-anchor: middle;
	}
	.mark {
		fill: var(--brass);
		transition: opacity 0.1s ease;
	}
	.mark-ring {
		fill: var(--ink-surface);
		transition: opacity 0.1s ease;
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
	.footnote {
		font-size: var(--fs-12);
		color: var(--bone-faint);
		margin: var(--sp-3) 0 0;
		line-height: 1.6;
	}
	.footnote strong {
		color: var(--bone-muted);
		font-weight: 400;
		font-style: italic;
	}
</style>
