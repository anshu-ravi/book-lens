<script lang="ts">
	import { onMount } from 'svelte';
	import { getGoodreadsStats, ApiError } from '$lib/api';
	import type { GoodreadsStatsResponse } from '$lib/types';
	import ChartCard from '$lib/components/stats/ChartCard.svelte';
	import StatTile from '$lib/components/stats/StatTile.svelte';
	import CoverStrip from '$lib/components/stats/CoverStrip.svelte';
	import YearChips from '$lib/components/stats/YearChips.svelte';
	import ReadingTimelineChart from '$lib/components/stats/ReadingTimelineChart.svelte';
	import AuthorsBarChart from '$lib/components/stats/AuthorsBarChart.svelte';
	import GenresBarChart from '$lib/components/stats/GenresBarChart.svelte';
	import GenreRatingDotPlot from '$lib/components/stats/GenreRatingDotPlot.svelte';
	import DecadeColumnChart from '$lib/components/stats/DecadeColumnChart.svelte';
	import { monthYear } from '$lib/components/stats/chartUtils';

	let stats = $state<GoodreadsStatsResponse | null>(null);
	let loading = $state(true);
	let loadError = $state('');

	let timelineMeasure = $state<'books' | 'pages'>('books');
	let timelineYear = $state<'all' | number>('all');
	let stripYear = $state<'all' | number>('all');

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

	let stripData = $derived.by(() => {
		if (!stats) return [];
		if (stripYear === 'all') return stats.by_month;
		return stats.by_month.filter((d) => monthYear(d.month) === stripYear);
	});

	// A fact about the coverage of the strip, not an apology for it: some read
	// books have no recorded finish date and so cannot be placed on a month.
	let stripSubtitle = $derived.by(() => {
		if (!stats) return undefined;
		const { with_date_read, read_total } = stats.coverage;
		const missing = read_total - with_date_read;
		if (missing <= 0) return `${with_date_read} read books, placed by month.`;
		return `${with_date_read} of ${read_total} read books have a recorded finish date and appear here; ${missing} do not.`;
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

		<ChartCard title="Books read, by month" subtitle={stripSubtitle}>
			{#snippet controls()}
				<YearChips {years} value={stripYear} onchange={(v) => (stripYear = v)} />
			{/snippet}
			<CoverStrip data={stripData} />
		</ChartCard>

		<div class="card-grid">
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
				<YearChips {years} value={timelineYear} onchange={(v) => (timelineYear = v)} />
				<ReadingTimelineChart data={timelineData} measure={timelineMeasure} />
			</ChartCard>

			<ChartCard title="Most-read authors">
				<AuthorsBarChart data={stats.top_authors} />
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
		container-type: inline-size;
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
	/* Capped at 3 columns -- auto-fit can't express a maximum, so the
	   breakpoints are explicit. Each threshold is the container width at
	   which one more 320px track (the existing minimum) plus its gap
	   still fits: 2*320+24 = 664px, 3*320+2*24 = 1008px. Below 664px a
	   single column keeps every card at or above the 320px minimum. */
	.card-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: var(--sp-6);
	}
	@container (min-width: 664px) {
		.card-grid {
			grid-template-columns: repeat(2, minmax(320px, 1fr));
		}
	}
	@container (min-width: 1008px) {
		.card-grid {
			grid-template-columns: repeat(3, minmax(320px, 1fr));
		}
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
</style>
