<script lang="ts">
	import type { Book, SeriesGroup } from '$lib/types';
	import BookCover from './BookCover.svelte';
	import ProgressBar from './ProgressBar.svelte';
	import StateChip from './StateChip.svelte';
	import IconButton from './IconButton.svelte';

	let {
		book,
		series,
		onedit,
		onask,
	}: {
		book: Book;
		series: SeriesGroup;
		onedit: (book: Book, focus: 'details' | 'reading') => void;
		onask: (book: Book) => void;
	} = $props();
</script>

<div class="carousel-item">
	<div class="card">
		<div class="cover-row">
			<BookCover
				title={book.title}
				author={book.author}
				seriesId={series.id}
				positionInSeries={book.book_order}
				size="small"
				coverUrl={book.has_cover ? `/api/books/${book.id}/cover` : null}
			/>
		</div>
		<div class="title">{book.title}</div>
		<div class="author">{book.author ? `by ${book.author}` : ''}</div>
		<div class="chip-row"><StateChip status={book.status} /></div>
		<div class="progress-wrap">
			<ProgressBar percent={book.percent} />
			<span class="pct mono">{book.percent}%</span>
		</div>
		<div class="actions">
			<IconButton icon="bookmark" label="Update reading position" onclick={() => onedit(book, 'reading')} />
			<IconButton icon="chat" label="Ask about this book" tone="brass" onclick={() => onask(book)} />
			<IconButton icon="pencil" label="Edit details & shelf" onclick={() => onedit(book, 'details')} />
		</div>
	</div>
</div>

<style>
	.card {
		width: 168px;
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-cover);
		padding: var(--sp-3);
	}
	.cover-row {
		display: flex;
		justify-content: center;
	}
	.title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-16);
		color: var(--bone);
		line-height: 1.25;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
		min-height: calc(1.25em * 2);
	}
	.author {
		font-family: var(--serif-body);
		font-size: var(--fs-13);
		color: var(--bone-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-height: 1.3em;
		line-height: 1.3;
	}
	.chip-row {
		display: flex;
	}
	.progress-wrap {
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
		margin-top: auto;
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding-top: var(--sp-2);
	}
</style>
