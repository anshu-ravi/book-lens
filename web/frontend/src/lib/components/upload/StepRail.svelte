<script lang="ts">
	let { step }: { step: 1 | 2 | 3 } = $props();

	const steps = [
		{ n: 1, roman: 'I', label: 'Drop the file' },
		{ n: 2, roman: 'II', label: 'Confirm the catalog entry' },
		{ n: 3, roman: 'III', label: 'Place on the shelf' },
	];
</script>

<nav class="rail">
	<span class="small-caps rail-heading">Acquisition</span>
	<ol>
		{#each steps as s}
			<li class:current={s.n === step} class:done={s.n < step}>
				<span class="roman">{s.roman}.</span>
				<span class="label" class:underline={s.n === step}>{s.label}</span>
				{#if s.n < step}<span class="small-caps done-tag">Done</span>{/if}
			</li>
		{/each}
	</ol>
	<p class="rail-note">
		Books in the same series share a reading timeline, so a volume filed under the wrong series
		will not see its predecessors.
	</p>
</nav>

<style>
	.rail {
		width: 220px;
		flex-shrink: 0;
	}
	.rail-heading {
		color: var(--brass);
		display: block;
		margin-bottom: var(--sp-6);
	}
	ol {
		list-style: none;
		margin: 0 0 var(--sp-8);
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}
	li {
		display: flex;
		align-items: baseline;
		gap: var(--sp-2);
		color: var(--bone-faint);
	}
	li.current,
	li.done {
		color: var(--bone);
	}
	.roman {
		font-family: var(--serif-display);
		font-style: italic;
		color: var(--oxblood);
		flex-shrink: 0;
	}
	.label.underline {
		text-decoration: underline;
		text-underline-offset: 4px;
		text-decoration-color: var(--brass);
	}
	.done-tag {
		color: var(--bone-faint);
		margin-left: auto;
	}
	.rail-note {
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--bone-muted);
		line-height: 1.5;
	}
</style>
