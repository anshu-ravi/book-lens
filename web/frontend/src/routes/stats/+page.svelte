<script lang="ts">
	import { onMount } from 'svelte';
	import { getGoodreadsStats, ApiError } from '$lib/api';
	import type { GoodreadsStatsResponse } from '$lib/types';
	import StatsHeadline from '$lib/components/stats/StatsHeadline.svelte';
	import MonthlyBarChart from '$lib/components/stats/MonthlyBarChart.svelte';
	import AuthorsBarChart from '$lib/components/stats/AuthorsBarChart.svelte';
	import DecadeBarChart from '$lib/components/stats/DecadeBarChart.svelte';
	import SeriesList from '$lib/components/stats/SeriesList.svelte';

	let stats = $state<GoodreadsStatsResponse | null>(null);
	let loading = $state(true);
	let loadError = $state('');

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
		<a href="/goodreads" class="small-caps sync-link">Go to Goodreads →</a>
	</div>
{:else if stats}
	<div class="sections">
		<section>
			<StatsHeadline totals={stats.totals} byMonth={stats.by_month} />
		</section>

		<div class="rule"></div>

		<section>
			<h2 class="small-caps section-label">Books and pages per month</h2>
			<MonthlyBarChart data={stats.by_month} coverage={stats.coverage} />
		</section>

		<div class="rule"></div>

		<section>
			<h2 class="small-caps section-label">Most-read authors</h2>
			<AuthorsBarChart data={stats.top_authors} />
		</section>

		<div class="rule"></div>

		<section>
			<h2 class="small-caps section-label">When your books were published</h2>
			<DecadeBarChart data={stats.by_decade} />
		</section>

		<div class="rule"></div>

		<section>
			<h2 class="small-caps section-label">Series</h2>
			<SeriesList data={stats.series} />
		</section>
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
		color: var(--brass);
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
	.sections {
		display: flex;
		flex-direction: column;
		gap: var(--sp-8);
	}
	.rule {
		height: 1px;
		background: var(--ink-hairline);
	}
	.section-label {
		color: var(--brass);
		display: block;
		margin: 0 0 var(--sp-4);
	}
</style>
