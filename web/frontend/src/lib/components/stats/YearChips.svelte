<script lang="ts">
	// Shared "All + one chip per year present" filter control, used by every
	// chart that lets the reader narrow the timeline to a single year.
	let {
		years,
		value,
		onchange,
	}: {
		years: number[];
		value: 'all' | number;
		onchange: (v: 'all' | number) => void;
	} = $props();
</script>

<div class="year-chips small-caps">
	<button type="button" class:active={value === 'all'} onclick={() => onchange('all')}>
		All
	</button>
	{#each years as y (y)}
		<button type="button" class:active={value === y} onclick={() => onchange(y)}>
			{y}
		</button>
	{/each}
</div>

<style>
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
</style>
