<script lang="ts">
	import type { Snippet } from 'svelte';

	// x, y are the anchor point in the plot wrapper's own pixel coordinates
	// (the wrapper must be position: relative). containerWidth decides which
	// side of the cursor the panel opens on so it never runs off the card.
	let {
		x,
		y,
		containerWidth,
		children,
	}: { x: number; y: number; containerWidth: number; children: Snippet } = $props();

	let flip = $derived(containerWidth > 0 && x > containerWidth * 0.6);
</script>

<div class="chart-tooltip" class:flip style="left: {x}px; top: {y}px;">
	<div class="tooltip-panel">
		{@render children()}
	</div>
</div>

<style>
	.chart-tooltip {
		position: absolute;
		pointer-events: none;
		transform: translate(12px, -50%);
		z-index: 5;
	}
	.chart-tooltip.flip {
		transform: translate(calc(-100% - 12px), -50%);
	}
	.tooltip-panel {
		background: var(--ink-bg);
		border: var(--hairline);
		border-radius: var(--r-chip);
		padding: var(--sp-2) var(--sp-3);
		font-family: var(--mono);
		font-variant-numeric: tabular-nums;
		font-size: var(--fs-12);
		color: var(--bone);
		white-space: nowrap;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
	}
</style>
