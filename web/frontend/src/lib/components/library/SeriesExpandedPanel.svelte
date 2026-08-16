<script lang="ts">
	import type { Book, SeriesGroup } from '$lib/types';
	import BookCover from './BookCover.svelte';
	import ProgressBar from './ProgressBar.svelte';
	import StateChip from './StateChip.svelte';

	let {
		series,
		onupdate,
		onask,
		onshelf,
	}: {
		series: SeriesGroup;
		onupdate: (book: Book) => void;
		onask: (book: Book) => void;
		onshelf: (book: Book) => void;
	} = $props();

	const sorted = $derived([...series.books].sort((a, b) => a.book_order - b.book_order));
</script>

<div class="panel">
	{#each sorted as book (book.id)}
		<div class="book">
			<BookCover
				title={book.title}
				author={book.author}
				seriesId={series.id}
				positionInSeries={book.book_order}
				size="medium"
				coverUrl={book.has_cover ? `/api/books/${book.id}/cover` : null}
			/>
			<div class="title">{book.title}</div>
			<StateChip status={book.status} />
			<div class="progress-wrap">
				<ProgressBar percent={book.percent} />
				<span class="pct mono">{book.percent}%</span>
			</div>
			<div class="actions">
				<button class="link-btn small-caps" onclick={() => onupdate(book)}>Update progress</button>
				<button class="link-btn small-caps brass" onclick={() => onask(book)}>Ask about this</button>
				<button class="link-btn small-caps" onclick={() => onshelf(book)}>Edit shelf</button>
			</div>
		</div>
	{/each}
</div>

<style>
	.panel {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-8);
		padding: var(--sp-6) 0;
		border-top: var(--hairline);
		margin-top: var(--sp-2);
	}
	.book {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		align-items: flex-start;
		width: 160px;
	}
	.title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-16);
		color: var(--bone);
		line-height: 1.25;
	}
	.progress-wrap {
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}
	.progress-wrap :global(.track) {
		flex: 1;
	}
	.pct {
		font-size: var(--fs-13);
		color: var(--brass);
		flex-shrink: 0;
	}
	.actions {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.link-btn {
		background: none;
		border: none;
		color: var(--bone-muted);
		text-decoration: underline;
		text-underline-offset: 3px;
		cursor: pointer;
		padding: 0;
	}
	.link-btn.brass {
		color: var(--brass);
	}
</style>
