<script lang="ts">
	import type { Book, SeriesGroup } from '$lib/types';
	import { seriesName } from '$lib/utils/series-name';
	import Carousel from './Carousel.svelte';
	import BookCard from './BookCard.svelte';
	import IconButton from './IconButton.svelte';

	let {
		series,
		onclose,
		onedit,
		onask,
	}: {
		series: SeriesGroup;
		onclose: () => void;
		onedit: (book: Book, focus: 'details' | 'reading') => void;
		onask: (book: Book) => void;
	} = $props();

	const sorted = $derived([...series.books].sort((a, b) => a.book_order - b.book_order));
	const finishedCount = $derived(series.books.filter((b) => b.status === 'finished').length);
</script>

<div class="overlay">
	<button type="button" class="overlay-dismiss" aria-label="Close" onclick={onclose}></button>
	<div class="modal" role="dialog" aria-modal="true" aria-label="{seriesName(series.id)} volumes">
		<div class="modal-header">
			<div>
				<h2 class="modal-title">{seriesName(series.id)}</h2>
				<div class="counts small-caps">
					{series.books.length} vol. · {finishedCount}/{series.books.length} finished
				</div>
			</div>
			<IconButton icon="close" label="Close" onclick={onclose} />
		</div>
		<div class="modal-body">
			<Carousel>
				{#each sorted as book (book.id)}
					<BookCard {book} {series} {onedit} {onask} />
				{/each}
			</Carousel>
		</div>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: var(--sp-4);
	}
	.overlay-dismiss {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		border: none;
		padding: 0;
		background: color-mix(in srgb, var(--ink-bg) 80%, transparent);
		cursor: default;
	}
	.modal {
		position: relative;
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-cover);
		padding: var(--sp-8);
		width: min(880px, 100%);
		max-height: 85vh;
		overflow: hidden;
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
	}
	.modal-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-4);
	}
	.modal-title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-28);
		margin: 0 0 var(--sp-2);
		color: var(--bone);
	}
	.counts {
		color: var(--bone-muted);
	}
	/* Visible, not hidden: the carousel's own track scrolls, and its arrows sit
	   just outside the cards. */
	.modal-body {
		overflow: visible;
	}
</style>
