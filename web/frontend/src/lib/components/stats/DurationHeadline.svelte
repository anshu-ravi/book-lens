<script lang="ts">
	import type { GoodreadsStatsDurations, GoodreadsStatsCoverage } from '$lib/types';

	let {
		durations,
		coverage,
	}: { durations?: GoodreadsStatsDurations; coverage: GoodreadsStatsCoverage } = $props();

	let count = $derived(durations?.count ?? 0);
</script>

{#if count === 0}
	<p class="empty-note">
		Start dates haven't been imported yet — run enrichment to see how long books take you.
	</p>
{:else}
	<div class="tiles">
		<div class="tile">
			<span class="value">{durations?.median_days}</span>
			<span class="small-caps label">Median days to finish</span>
		</div>
		<div class="tile">
			<span class="value">{durations?.fastest?.days}</span>
			<span class="small-caps label">Fastest</span>
			<span class="sub-label">{durations?.fastest?.title}</span>
		</div>
		<div class="tile">
			<span class="value">{durations?.slowest?.days}</span>
			<span class="small-caps label">Slowest</span>
			<span class="sub-label">{durations?.slowest?.title}</span>
		</div>
	</div>

	<p class="coverage-note">
		Covers {coverage.with_date_started ?? 0} of {coverage.read_total} read books with a recorded
		start date.
	</p>
{/if}

<style>
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: var(--sp-6);
	}
	.tile {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.value {
		font-family: var(--serif-display);
		font-size: var(--fs-40);
		color: var(--bone);
		line-height: 1;
	}
	.label {
		color: var(--brass);
	}
	.sub-label {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-14);
		color: var(--bone-muted);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
	.coverage-note {
		font-size: var(--fs-12);
		color: var(--bone-faint);
		margin: var(--sp-2) 0 0;
	}
</style>
