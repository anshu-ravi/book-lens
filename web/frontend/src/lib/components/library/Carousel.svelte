<script lang="ts">
	let { children }: { children: import('svelte').Snippet } = $props();
</script>

<div
	class="carousel-track"
	onwheel={(e: WheelEvent) => {
		if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
		(e.currentTarget as HTMLDivElement).scrollBy({ left: e.deltaY, behavior: 'auto' });
	}}
>
	{@render children()}
</div>

<style>
	.carousel-track {
		display: flex;
		gap: var(--sp-6);
		overflow-x: auto;
		overflow-y: hidden;
		scroll-snap-type: x proximity;
		padding-bottom: var(--sp-3);
		scrollbar-width: thin;
		scrollbar-color: var(--brass-dim) transparent;
	}
	.carousel-track::-webkit-scrollbar {
		height: 6px;
	}
	.carousel-track::-webkit-scrollbar-track {
		background: transparent;
	}
	.carousel-track::-webkit-scrollbar-thumb {
		background: var(--brass-dim);
		border-radius: 3px;
	}
	:global(.carousel-item) {
		scroll-snap-align: start;
		flex-shrink: 0;
	}
</style>
