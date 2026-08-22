<script lang="ts">
	import type { GoodreadsStatsGenreRating } from '$lib/types';

	let { data }: { data: GoodreadsStatsGenreRating[] } = $props();

	const W = 480;
	const ROW_H = 26;
	const ML = 150;
	const MR = 60;
	const MT = 6;
	const MAX_RATING = 5;

	let n = $derived(data.length);
	let H = $derived(MT * 2 + n * ROW_H);
	let barMaxWidth = $derived(W - ML - MR);
</script>

<figure class="chart-figure">
	{#if n === 0}
		<p class="empty-note">Genres haven't been imported yet — run enrichment to see ratings by genre.</p>
	{:else}
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-labelledby="genre-rating-chart-title"
		>
			<title id="genre-rating-chart-title">Average rating by genre, out of 5</title>
			{#each data as g, i (g.genre)}
				{@const y = MT + i * ROW_H}
				{@const width = (g.avg_rating / MAX_RATING) * barMaxWidth}
				<text x={ML - 10} y={y + ROW_H / 2 + 4} class="genre-label">{g.genre}</text>
				<rect x={ML} y={y + 4} width={barMaxWidth} height={ROW_H - 10} class="bar-track" />
				<rect x={ML} y={y + 4} {width} height={ROW_H - 10} class="bar" />
				<text x={ML + width + 8} y={y + ROW_H / 2 + 4} class="value-label">
					{g.avg_rating.toFixed(1)} ({g.books})
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
	.genre-label {
		font-family: var(--serif-body);
		font-size: 10px;
		fill: var(--bone-muted);
		text-anchor: end;
	}
	.bar-track {
		fill: var(--ink-hairline);
	}
	.bar {
		fill: var(--sage);
	}
	.value-label {
		font-family: var(--mono);
		font-size: 9px;
		fill: var(--bone-faint);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
	}
</style>
