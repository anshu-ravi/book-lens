<script lang="ts">
	import type { GoodreadsStatsSeries } from '$lib/types';

	let { data }: { data: GoodreadsStatsSeries[] } = $props();

	function isPartial(s: GoodreadsStatsSeries): boolean {
		return s.read > 0 && s.read < s.total;
	}
</script>

{#if data.length === 0}
	<p class="empty-note">No series found among your cached books.</p>
{:else}
	<ul class="series-list">
		{#each data as s (s.name)}
			{@const partial = isPartial(s)}
			<li class="series-row" class:partial class:complete={!partial}>
				<span class="name">{s.name}</span>
				<div class="progress-track" role="img" aria-label="{s.read} of {s.total} read">
					<div class="progress-fill" style="width: {(s.read / s.total) * 100}%"></div>
				</div>
				<span class="fraction small-caps">{s.read}/{s.total}</span>
			</li>
		{/each}
	</ul>
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
		grid-template-columns: minmax(120px, 1fr) minmax(80px, 160px) auto;
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
	}
	.series-row.complete .name {
		color: var(--bone-muted);
	}
	.progress-track {
		height: 5px;
		background: var(--ink-hairline);
		border-radius: var(--r-chip);
		overflow: hidden;
	}
	.progress-fill {
		height: 100%;
	}
	.series-row.partial .progress-fill {
		background: var(--brass);
	}
	.series-row.complete .progress-fill {
		background: var(--sage);
	}
	.fraction {
		font-family: var(--mono);
		color: var(--bone-faint);
		text-align: right;
	}
	.series-row.partial .fraction {
		color: var(--brass);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
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
		.progress-track {
			grid-area: track;
		}
	}
</style>
