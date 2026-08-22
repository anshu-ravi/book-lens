<script lang="ts">
	import type { GoodreadsStatsSeries } from '$lib/types';

	let { data }: { data: GoodreadsStatsSeries[] } = $props();

	const VISIBLE_CAP = 8;

	let showAll = $state(false);

	let visible = $derived(showAll ? data : data.slice(0, VISIBLE_CAP));
	let hiddenCount = $derived(Math.max(0, data.length - VISIBLE_CAP));
</script>

{#if data.length === 0}
	<p class="empty-note">No series found among your cached books.</p>
{:else}
	<ul class="series-list">
		{#each visible as s (s.name)}
			<li class="series-row">
				<span class="name">{s.name}</span>
				<div
					class="meter-track"
					role="img"
					aria-label="{s.read} of the {s.total} volumes in your library read"
				>
					<div class="meter-fill" style="width: {(s.read / s.total) * 100}%"></div>
				</div>
				<span class="fraction small-caps">{s.read} read · {s.total} in your library</span>
			</li>
		{/each}
	</ul>

	{#if hiddenCount > 0}
		<button type="button" class="small-caps show-all" onclick={() => (showAll = !showAll)}>
			{showAll ? 'Show fewer' : `Show all (${data.length})`}
		</button>
	{/if}
{/if}

<style>
	.series-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
	}
	.series-row {
		display: grid;
		grid-template-columns: minmax(100px, 1fr) minmax(80px, 160px) auto;
		align-items: center;
		gap: var(--sp-4);
		padding: var(--sp-2) 0;
		border-bottom: var(--hairline);
	}
	.series-row:last-child {
		border-bottom: none;
	}
	.name {
		font-family: var(--serif-body);
		color: var(--bone);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.meter-track {
		height: 6px;
		background: var(--brass-dim);
		border-radius: var(--r-chip);
		overflow: hidden;
	}
	.meter-fill {
		height: 100%;
		background: var(--brass);
	}
	.fraction {
		font-family: var(--mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--fs-12);
		color: var(--bone-faint);
		text-align: right;
		white-space: nowrap;
	}
	.show-all {
		margin-top: var(--sp-3);
		background: none;
		border: none;
		padding: 0;
		color: var(--brass-text);
		cursor: pointer;
	}
	.show-all:hover {
		text-decoration: underline;
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
	@media (max-width: 500px) {
		.series-row {
			grid-template-columns: 1fr auto;
			grid-template-areas: 'name fraction' 'track track';
			row-gap: var(--sp-1);
		}
		.name {
			grid-area: name;
		}
		.fraction {
			grid-area: fraction;
		}
		.meter-track {
			grid-area: track;
		}
	}
</style>
