<script lang="ts">
	let { children }: { children: import('svelte').Snippet } = $props();

	let trackEl: HTMLDivElement | undefined = $state();
	const DRAG_THRESHOLD = 5;

	let dragging = $state(false);
	let pressed = false;
	let justDragged = false;
	let startX = 0;
	let startScrollLeft = 0;

	let canScrollLeft = $state(false);
	let canScrollRight = $state(false);

	function updateArrows() {
		if (!trackEl) return;
		canScrollLeft = trackEl.scrollLeft > 0;
		canScrollRight = trackEl.scrollLeft + trackEl.clientWidth < trackEl.scrollWidth - 1;
	}

	$effect(() => {
		if (!trackEl) return;
		const ro = new ResizeObserver(updateArrows);
		ro.observe(trackEl);
		updateArrows();
		return () => ro.disconnect();
	});

	function scrollByStep(dir: 1 | -1) {
		if (!trackEl) return;
		trackEl.scrollBy({ left: dir * trackEl.clientWidth * 0.8, behavior: 'smooth' });
	}

	function onPointerDown(e: PointerEvent) {
		if (!trackEl) return;
		justDragged = false;
		pressed = true;
		startX = e.clientX;
		startScrollLeft = trackEl.scrollLeft;
	}

	function onPointerMove(e: PointerEvent) {
		if (!pressed || !trackEl) return;
		const dx = e.clientX - startX;
		if (Math.abs(dx) <= DRAG_THRESHOLD) return;
		// Captured only once the press is unambiguously a drag: capturing on
		// pointerdown retargets the click and swallows the card's own buttons.
		if (!dragging) {
			dragging = true;
			justDragged = true;
			trackEl.setPointerCapture(e.pointerId);
		}
		trackEl.scrollLeft = startScrollLeft - dx;
	}

	function endDrag() {
		pressed = false;
		dragging = false;
	}

	function onTrackClickCapture(e: MouseEvent) {
		if (justDragged) {
			e.stopPropagation();
		}
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'ArrowRight') {
			e.preventDefault();
			scrollByStep(1);
		} else if (e.key === 'ArrowLeft') {
			e.preventDefault();
			scrollByStep(-1);
		}
	}
</script>

<div class="carousel-wrap">
	{#if canScrollLeft}
		<button type="button" class="arrow arrow-left" aria-label="Scroll left" onclick={() => scrollByStep(-1)}>
			<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M10 3 5 8l5 5" />
			</svg>
		</button>
	{/if}
	<!-- A scrollable region is legitimately focusable and drag/key driven; the
	     cards inside it carry the interactive roles. -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="carousel-track"
		class:dragging
		bind:this={trackEl}
		tabindex="0"
		role="group"
		onwheel={(e: WheelEvent) => {
			if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
			(e.currentTarget as HTMLDivElement).scrollBy({ left: e.deltaY, behavior: 'auto' });
		}}
		onscroll={updateArrows}
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={endDrag}
		onpointercancel={endDrag}
		onpointerleave={endDrag}
		onclickcapture={onTrackClickCapture}
		onkeydown={onKeydown}
	>
		{@render children()}
	</div>
	{#if canScrollRight}
		<button type="button" class="arrow arrow-right" aria-label="Scroll right" onclick={() => scrollByStep(1)}>
			<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M6 3l5 5-5 5" />
			</svg>
		</button>
	{/if}
</div>

<style>
	.carousel-wrap {
		position: relative;
	}
	.carousel-track {
		display: flex;
		align-items: stretch;
		gap: var(--sp-6);
		overflow-x: auto;
		overflow-y: hidden;
		scroll-snap-type: x proximity;
		padding: var(--sp-6) var(--sp-2) var(--sp-3);
		margin: calc(var(--sp-6) * -1) calc(var(--sp-2) * -1) 0;
		scrollbar-width: thin;
		scrollbar-color: var(--brass-dim) transparent;
		cursor: grab;
	}
	.carousel-track.dragging {
		cursor: grabbing;
		user-select: none;
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
	/* display:flex gives the card inside a definite height to stretch into, so
	   cards in a row align however long their titles are. */
	:global(.carousel-item) {
		scroll-snap-align: start;
		flex-shrink: 0;
		display: flex;
	}
	.arrow {
		position: absolute;
		top: 50%;
		transform: translateY(-50%);
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--ink-surface);
		border: var(--hairline);
		color: var(--bone-muted);
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		z-index: 10;
		transition: color 0.15s;
	}
	.arrow:hover {
		color: var(--brass);
	}
	.arrow-left {
		left: -10px;
	}
	.arrow-right {
		right: -10px;
	}
</style>
