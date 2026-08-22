<script lang="ts">
	let { value, label }: { value: string; label: string } = $props();
</script>

<div class="stat-tile">
	<span class="value">{value}</span>
	<span class="small-caps label">{label}</span>
</div>

<style>
	.stat-tile {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		padding: var(--sp-3);
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-card);
		min-width: 0;
	}
	.value {
		font-family: var(--serif-display);
		font-size: var(--fs-28);
		color: var(--bone);
		line-height: 1;
		font-variant-numeric: tabular-nums;
	}
	.label {
		color: var(--brass-text);
	}
</style>
