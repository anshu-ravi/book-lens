<script lang="ts">
	import type { GoodreadsStatsTotals, GoodreadsStatsMonth } from '$lib/types';

	let { totals, byMonth }: { totals: GoodreadsStatsTotals; byMonth: GoodreadsStatsMonth[] } =
		$props();

	// Pace: pages read per month spanned by the recorded reading history.
	// `byMonth` is already gap-filled, so its length is the month span.
	let paceSentence = $derived.by(() => {
		const monthsSpanned = byMonth.length;
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
		const years = horizonMonths / 12;
		return `At your current pace, about ${years.toFixed(1)} years of reading is waiting on the shelf.`;
	});
</script>

<section class="headline">
	<div class="tiles">
		<div class="tile">
			<span class="value">{totals.books_read}</span>
			<span class="small-caps label">Books read</span>
		</div>
		<div class="tile">
			<span class="value">{totals.pages_read.toLocaleString()}</span>
			<span class="small-caps label">Pages read</span>
		</div>
		<div class="tile">
			<span class="value">{totals.avg_pages.toLocaleString()}</span>
			<span class="small-caps label">Average length</span>
		</div>
		<div class="tile">
			<span class="value">{totals.dnf}</span>
			<span class="small-caps label">Did not finish</span>
		</div>
	</div>

	<p class="pace">
		{paceSentence}
		{#if totals.want_to_read > 0}
			<span class="backlog-count">{totals.want_to_read.toLocaleString()} books, {totals.backlog_pages.toLocaleString()} pages.</span>
		{/if}
	</p>
</section>

<style>
	.headline {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}
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
	.pace {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone-muted);
		margin: 0;
		max-width: 640px;
	}
	.backlog-count {
		display: block;
		font-family: var(--sans-caps);
		font-style: normal;
		font-size: var(--fs-13);
		color: var(--bone-faint);
		margin-top: var(--sp-1);
	}
</style>
