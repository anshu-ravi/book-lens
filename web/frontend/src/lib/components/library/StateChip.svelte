<script lang="ts">
	import type { BookStatus } from '$lib/types';

	let {
		status,
		percent,
		overlay = false,
	}: { status: BookStatus; percent?: number; overlay?: boolean } = $props();

	const labels: Record<BookStatus, string> = {
		unread: 'UNREAD',
		reading: 'IN PROGRESS',
		finished: 'FINISHED',
	};

	const label = $derived(
		status === 'reading' && percent !== undefined ? `${labels.reading} · ${percent}%` : labels[status],
	);
</script>

<span
	class="chip"
	class:overlay
	class:unread={status === 'unread'}
	class:reading={status === 'reading'}
	class:finished={status === 'finished'}
>
	{label}
</span>

<style>
	.chip {
		display: inline-block;
		font-family: var(--sans-caps);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		font-size: 10px;
		padding: 2px 6px;
		border-radius: var(--r-chip);
		background: color-mix(in srgb, var(--chip-color) 15%, transparent);
		color: var(--chip-color);
	}
	.chip.unread {
		--chip-color: var(--bone-muted);
	}
	.chip.reading {
		--chip-color: var(--brass);
	}
	.chip.finished {
		--chip-color: var(--sage);
	}
	.chip.overlay {
		position: absolute;
		top: 6px;
		left: 6px;
		font-size: 10px;
		background: color-mix(in srgb, var(--ink-bg) 65%, transparent);
		backdrop-filter: blur(4px);
		-webkit-backdrop-filter: blur(4px);
		color: var(--chip-color);
	}
</style>
