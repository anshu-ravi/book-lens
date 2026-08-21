<script lang="ts">
	import type { GoodreadsStatsDecade } from '$lib/types';

	let { data }: { data: GoodreadsStatsDecade[] } = $props();

	const W = 640;
	const H = 200;
	const ML = 30;
	const MR = 12;
	const MT = 10;
	const MB = 30;
	const innerW = W - ML - MR;
	const innerH = H - MT - MB;

	let n = $derived(data.length);
	let maxBooks = $derived(Math.max(1, ...data.map((d) => d.books)));
	let slot = $derived(n > 0 ? innerW / n : innerW);
	let barWidth = $derived(Math.max(3, slot * 0.6));
	let ticks = $derived([0, Math.round(maxBooks / 2), maxBooks]);
</script>

<figure class="chart-figure">
	{#if n === 0}
		<p class="empty-note">No publication years recorded yet.</p>
	{:else}
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-labelledby="decade-chart-title"
		>
			<title id="decade-chart-title">
				Books read by decade of original publication, {data[0].decade}s through {data[n - 1]
					.decade}s
			</title>

			{#each ticks as tick (tick)}
				{@const y = MT + innerH - (tick / maxBooks) * innerH}
				<line x1={ML} y1={y} x2={W - MR} y2={y} class="gridline" />
				<text x={ML - 6} y={y + 3} class="axis-label left">{tick}</text>
			{/each}

			{#each data as d, i (d.decade)}
				{@const h = (d.books / maxBooks) * innerH}
				{@const x = ML + i * slot + (slot - barWidth) / 2}
				{@const y = MT + innerH - h}
				<rect {x} {y} width={barWidth} height={h} class="bar" />
				<text x={ML + i * slot + slot / 2} y={H - MB + 16} class="axis-label decade">
					{d.decade}s
				</text>
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
	.axis-label.decade {
		text-anchor: middle;
	}
	.bar {
		fill: var(--brass);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
	}
</style>
