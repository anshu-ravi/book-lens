<script lang="ts">
	import type { GoodreadsStatsAuthor } from '$lib/types';

	let { data }: { data: GoodreadsStatsAuthor[] } = $props();

	const W = 480;
	const ROW_H = 26;
	const ML = 150;
	const MR = 30;
	const MT = 6;

	let n = $derived(data.length);
	let H = $derived(MT * 2 + n * ROW_H);
	let maxBooks = $derived(Math.max(1, ...data.map((d) => d.books)));
	let barMaxWidth = $derived(W - ML - MR);
</script>

<figure class="chart-figure">
	{#if n === 0}
		<p class="empty-note">No read books yet.</p>
	{:else}
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-labelledby="authors-chart-title"
		>
			<title id="authors-chart-title">Most-read authors, by number of books read</title>
			{#each data as a, i (a.author)}
				{@const y = MT + i * ROW_H}
				{@const width = (a.books / maxBooks) * barMaxWidth}
				<text x={ML - 10} y={y + ROW_H / 2 + 4} class="author-label">{a.author}</text>
				<rect x={ML} y={y + 4} width={barMaxWidth} height={ROW_H - 10} class="bar-track" />
				<rect x={ML} y={y + 4} {width} height={ROW_H - 10} class="bar" />
				<text x={ML + width + 8} y={y + ROW_H / 2 + 4} class="count-label">{a.books}</text>
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
	.author-label {
		font-family: var(--serif-body);
		font-size: 10px;
		fill: var(--bone-muted);
		text-anchor: end;
	}
	.bar-track {
		fill: var(--ink-hairline);
	}
	.bar {
		fill: var(--brass);
	}
	.count-label {
		font-family: var(--mono);
		font-size: 9px;
		fill: var(--bone-faint);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
	}
</style>
