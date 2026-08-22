<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		subtitle,
		span2 = false,
		controls,
		children,
	}: {
		title: string;
		subtitle?: string;
		span2?: boolean;
		controls?: Snippet;
		children: Snippet;
	} = $props();
</script>

<section class="chart-card" class:span2>
	<div class="card-head">
		<div class="card-head-text">
			<h3 class="small-caps card-title">{title}</h3>
			{#if subtitle}
				<p class="card-subtitle">{subtitle}</p>
			{/if}
		</div>
		{#if controls}
			<div class="card-controls">{@render controls()}</div>
		{/if}
	</div>
	<div class="card-body">
		{@render children()}
	</div>
</section>

<style>
	.chart-card {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		padding: var(--sp-4);
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-card);
		min-width: 0;
	}
	/* Gated behind a min-width so the span never forces the auto-fit grid to
	   keep a second track alive at widths where only one column actually
	   fits — an explicit span otherwise wins over auto-fit's own collapse. */
	@media (min-width: 1024px) {
		.chart-card.span2 {
			grid-column: span 2;
		}
	}
	.card-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-3);
	}
	.card-head-text {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		min-width: 0;
	}
	.card-title {
		color: var(--brass-text);
		margin: 0;
	}
	.card-subtitle {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--bone-muted);
		margin: 0;
	}
	.card-controls {
		flex-shrink: 0;
	}
	.card-body {
		min-width: 0;
	}
</style>
