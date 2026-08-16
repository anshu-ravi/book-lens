<script lang="ts">
	import type { BookStatus } from '$lib/types';

	let { status }: { status: BookStatus } = $props();

	const labels: Record<BookStatus, string> = {
		unread: 'UNREAD',
		reading: 'READING',
		finished: 'FINISHED',
	};
</script>

<span class="chip" class:unread={status === 'unread'} class:reading={status === 'reading'} class:finished={status === 'finished'}>
	{labels[status]}
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
</style>
