<script lang="ts">
	import type { GoodreadsStatsDurationBook } from '$lib/types';

	let { data }: { data: GoodreadsStatsDurationBook[] } = $props();

	const W = 640;
	const H = 320;
	const ML = 40;
	const MR = 16;
	const MT = 12;
	const MB = 40;
	const innerW = W - ML - MR;
	const innerH = H - MT - MB;

	let n = $derived(data.length);
	let maxPages = $derived(Math.max(1, ...data.map((d) => d.pages)));
	let minPages = $derived(Math.min(...data.map((d) => d.pages), 0));
	let maxDays = $derived(Math.max(1, ...data.map((d) => d.days)));
	let pagesRange = $derived(Math.max(1, maxPages - minPages));

	function scaleX(pages: number): number {
		return ML + ((pages - minPages) / pagesRange) * innerW;
	}
	function scaleY(days: number): number {
		return MT + innerH - (days / maxDays) * innerH;
	}

	let points = $derived(
		data.map((d) => ({
			x: scaleX(d.pages),
			y: scaleY(d.days),
			title: d.title,
			pages: d.pages,
			days: d.days,
		})),
	);

	let xTicks = $derived(
		[0, 0.5, 1].map((f) => Math.round(minPages + f * pagesRange)),
	);
	let yTicks = $derived([0, 0.5, 1].map((f) => Math.round(f * maxDays)));
</script>

<figure class="chart-figure">
	{#if n === 0}
		<p class="empty-note">No books with both a page count and a finish time yet.</p>
	{:else}
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-labelledby="duration-scatter-title"
		>
			<title id="duration-scatter-title">
				Days to finish plotted against book length, one mark per book
			</title>

			<!-- horizontal gridlines + y-axis (days) -->
			{#each yTicks as tick (tick)}
				{@const y = scaleY(tick)}
				<line x1={ML} y1={y} x2={W - MR} y2={y} class="gridline" />
				<text x={ML - 8} y={y + 3} class="axis-label left">{tick}</text>
			{/each}

			<!-- x-axis (pages) -->
			{#each xTicks as tick (tick)}
				{@const x = scaleX(tick)}
				<text x={x} y={H - MB + 16} class="axis-label bottom">{tick}</text>
			{/each}

			<!-- axis titles -->
			<text x={ML + innerW / 2} y={H - 6} class="axis-title">Pages</text>
			<text
				x={-(MT + innerH / 2)}
				y={12}
				class="axis-title"
				transform="rotate(-90)"
			>
				Days
			</text>

			{#each points as p, i (i)}
				<circle cx={p.x} cy={p.y} r="4" class="mark">
					<title>{p.title} — {p.pages} pages, {p.days} days</title>
				</circle>
			{/each}
		</svg>
	{/if}
</figure>

<style>
	.chart-figure {
		margin: 0;
	}
	svg {
		width: 100%;
		height: auto;
		display: block;
	}
	.gridline {
		stroke: var(--ink-hairline);
		stroke-width: 1;
	}
	.axis-label {
		font-family: var(--mono);
		font-size: 8px;
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
		font-size: 9px;
		letter-spacing: var(--tracking-caps);
		text-transform: uppercase;
		fill: var(--bone-muted);
		text-anchor: middle;
	}
	.mark {
		fill: var(--brass);
		fill-opacity: 0.6;
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
	}
</style>
