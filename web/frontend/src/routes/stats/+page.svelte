<script lang="ts">
	import { onMount } from 'svelte';
	import { getGoodreadsStats, ApiError } from '$lib/api';
	import type { GoodreadsStatsResponse } from '$lib/types';
	import ChartCard from '$lib/components/stats/ChartCard.svelte';
	import StatTile from '$lib/components/stats/StatTile.svelte';
	import ReadingTimelineChart from '$lib/components/stats/ReadingTimelineChart.svelte';
	import AuthorsBarChart from '$lib/components/stats/AuthorsBarChart.svelte';
	import GenresBarChart from '$lib/components/stats/GenresBarChart.svelte';
	import GenreRatingDotPlot from '$lib/components/stats/GenreRatingDotPlot.svelte';
	import DecadeColumnChart from '$lib/components/stats/DecadeColumnChart.svelte';
	import SeriesList from '$lib/components/stats/SeriesList.svelte';
	import LengthTimeScatter from '$lib/components/stats/LengthTimeScatter.svelte';
	import { monthYear } from '$lib/components/stats/chartUtils';

	let stats = $state<GoodreadsStatsResponse | null>(null);
	let loading = $state(true);
	let loadError = $state('');

	let timelineMeasure = $state<'books' | 'pages'>('books');
	let timelineYear = $state<'all' | number>('all');

	async function load() {
		loading = true;
		loadError = '';
		try {
			stats = await getGoodreadsStats();
		} catch (e) {
			loadError = e instanceof ApiError ? e.detail : 'Could not reach the Goodreads cache.';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	let isEmptyCache = $derived(
		stats !== null &&
			stats.totals.books_read === 0 &&
			stats.totals.want_to_read === 0 &&
			stats.totals.currently_reading === 0 &&
			stats.totals.dnf === 0,
	);

	let years = $derived.by(() => {
		if (!stats) return [];
		const set = new Set(stats.by_month.map((d) => monthYear(d.month)));
		return Array.from(set).sort((a, b) => a - b);
	});

	let timelineData = $derived.by(() => {
		if (!stats) return [];
		if (timelineYear === 'all') return stats.by_month;
		return stats.by_month.filter((d) => monthYear(d.month) === timelineYear);
	});

	// Pace: pages read per month spanned by the recorded reading history.
	// `by_month` is already gap-filled, so its length is the month span.
	let paceSentence = $derived.by(() => {
		if (!stats) return '';
		const { totals, by_month } = stats;
		const monthsSpanned = by_month.length;
		if (monthsSpanned === 0 || totals.pages_read === 0) {
			return 'Not enough reading history yet to project a pace.';
		}
		const pace = totals.pages_read / monthsSpanned;
		if (totals.backlog_pages === 0) {
			return "Nothing waiting on the shelf — you're caught up.";
		}
		if (pace <= 0) {
			return "At your current pace, the backlog isn't moving.";
		}
		const horizonMonths = totals.backlog_pages / pace;
		if (horizonMonths < 1.5) {
			return 'At your current pace, the backlog is a matter of weeks.';
		}
		if (horizonMonths < 20) {
			return `At your current pace, about ${Math.round(horizonMonths)} months of reading is waiting on the shelf.`;
		}
		const yrs = horizonMonths / 12;
		return `At your current pace, about ${yrs.toFixed(1)} years of reading is waiting on the shelf.`;
	});

	let scatterSubtitle = $derived.by(() => {
		if (!stats) return undefined;
		const covered = (stats.durations?.books ?? []).filter((d) => d.pages > 0).length;
		return `Covers ${covered} of ${stats.coverage.read_total} read books with both a page count and a finish time.`;
	});
</script>

<svelte:head>
	<title>BookLens · Stats</title>
</svelte:head>

<div class="greeting-strip">
	<span class="small-caps meta-line">Reading, in aggregate</span>
	<h1 class="display-line">Your stats</h1>
</div>

{#if loading}
	<p class="loading-text">Counting pages…</p>
{:else if loadError}
	<p class="error-text">{loadError}</p>
{:else if isEmptyCache}
	<div class="empty-state">
		<p>Nothing synced yet.</p>
		<a href="/library" class="small-caps sync-link">Go to library →</a>
	</div>
{:else if stats}
	<div class="stats-page">
		<div class="tile-row">
			<StatTile value={stats.totals.books_read.toLocaleString()} label="Books read" />
			<StatTile value={stats.totals.pages_read.toLocaleString()} label="Pages read" />
			<StatTile value={stats.totals.avg_pages.toLocaleString()} label="Average length" />
			<StatTile
				value={stats.durations && stats.durations.count > 0
					? String(stats.durations.median_days)
					: '—'}
				label="Median days to finish"
			/>
			<StatTile value={stats.totals.dnf.toLocaleString()} label="Did not finish" />
			<StatTile
				value="{stats.totals.want_to_read.toLocaleString()} / {stats.totals.backlog_pages.toLocaleString()}"
				label="To read (books / pages)"
			/>
		</div>
		<p class="pace">{paceSentence}</p>

		<ChartCard title="Reading over time">
			{#snippet controls()}
				<div class="segmented small-caps">
					<button
						type="button"
						class:active={timelineMeasure === 'books'}
						onclick={() => (timelineMeasure = 'books')}
					>
						Books
					</button>
					<button
						type="button"
						class:active={timelineMeasure === 'pages'}
						onclick={() => (timelineMeasure = 'pages')}
					>
						Pages
					</button>
				</div>
			{/snippet}
			<div class="year-chips small-caps">
				<button type="button" class:active={timelineYear === 'all'} onclick={() => (timelineYear = 'all')}>
					All
				</button>
				{#each years as y (y)}
					<button type="button" class:active={timelineYear === y} onclick={() => (timelineYear = y)}>
						{y}
					</button>
				{/each}
			</div>
			<ReadingTimelineChart data={timelineData} measure={timelineMeasure} />
		</ChartCard>

		<div class="card-grid">
			<ChartCard title="Most-read authors">
				<AuthorsBarChart data={stats.top_authors.slice(0, 8)} />
			</ChartCard>

			<ChartCard title="Genres" subtitle="Each book contributes up to three genres, so counts sum past the book total.">
				<GenresBarChart data={(stats.genres ?? []).slice(0, 8)} />
			</ChartCard>

			<ChartCard title="Ratings by genre">
				<GenreRatingDotPlot data={stats.rating_by_genre ?? []} />
			</ChartCard>

			<ChartCard title="Publication decade">
				<DecadeColumnChart data={stats.by_decade} />
			</ChartCard>

			<ChartCard title="Series" span2>
				<SeriesList data={stats.series} />
			</ChartCard>

			<ChartCard title="Length versus time" subtitle={scatterSubtitle} span2>
				{#if (stats.durations?.count ?? 0) === 0}
					<p class="empty-note">
						Start dates haven't been imported yet — run enrichment to see whether longer books
						take proportionally longer.
					</p>
				{:else}
					<LengthTimeScatter
						durations={stats.durations ?? { count: 0, median_days: 0, mean_days: 0, fastest: null, slowest: null, books: [] }}
					/>
				{/if}
			</ChartCard>
		</div>
	</div>
{/if}

<style>
	.loading-text,
	.error-text {
		font-style: italic;
		color: var(--bone-muted);
	}
	.error-text {
		color: var(--oxblood);
	}
	.empty-state {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		align-items: flex-start;
		padding: var(--sp-16) 0;
		max-width: 360px;
	}
	.empty-state p {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone-muted);
		margin: 0;
	}
	.sync-link {
		color: var(--brass);
		text-decoration: none;
	}
	.sync-link:hover {
		text-decoration: underline;
	}
	.greeting-strip {
		margin-bottom: var(--sp-12);
	}
	.meta-line {
		color: var(--brass-text);
		display: block;
		margin-bottom: var(--sp-2);
	}
	.display-line {
		font-family: var(--serif-display);
		font-style: italic;
		font-weight: 400;
		font-size: var(--fs-40);
		color: var(--bone);
		margin: 0;
	}
	.stats-page {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: var(--sp-8);
		min-width: 0;
	}
	.tile-row {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: var(--sp-4);
	}
	.pace {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-16);
		color: var(--bone-muted);
		margin: calc(-1 * var(--sp-4)) 0 0;
	}
	.card-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
		gap: var(--sp-6);
	}
	.segmented {
		display: inline-flex;
		border: var(--hairline);
		border-radius: var(--r-chip);
		overflow: hidden;
	}
	.segmented button {
		background: none;
		border: none;
		padding: var(--sp-1) var(--sp-3);
		color: var(--bone-muted);
		cursor: pointer;
		font: inherit;
		letter-spacing: inherit;
		text-transform: inherit;
	}
	.segmented button + button {
		border-left: var(--hairline);
	}
	.segmented button.active {
		background: var(--brass-dim);
		color: var(--brass-text);
	}
	.year-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}
	.year-chips button {
		background: none;
		border: var(--hairline);
		border-radius: var(--r-chip);
		padding: var(--sp-1) var(--sp-2);
		color: var(--bone-muted);
		cursor: pointer;
		font: inherit;
		letter-spacing: inherit;
		text-transform: inherit;
	}
	.year-chips button.active {
		background: var(--brass-dim);
		color: var(--brass-text);
		border-color: var(--brass);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
</style>
