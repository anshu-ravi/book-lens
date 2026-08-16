<script lang="ts">
	import type { Book, SeriesGroup } from '$lib/types';
	import { seriesName } from '$lib/utils/series-name';
	import BookCover from './BookCover.svelte';
	import ProgressBar from './ProgressBar.svelte';

	let {
		book,
		series,
		onupdate,
		onask,
	}: {
		book: Book;
		series: SeriesGroup;
		onupdate: (book: Book) => void;
		onask: (book: Book) => void;
	} = $props();

	const seriesLabel = $derived(`${seriesName(series.id)} · VOLUME ${book.book_order}/${series.books.length}`);
</script>

<div class="card">
	<button class="cover-col" onclick={() => onupdate(book)} aria-label="Update progress for {book.title}">
		<BookCover title={book.title} author={book.author} seriesId={series.id} positionInSeries={book.book_order} size="medium" />
	</button>
	<div class="meta-col">
		<div class="series-label small-caps">{seriesLabel}</div>
		<div class="title">{book.title}</div>
		{#if book.author}
			<div class="author">by {book.author}</div>
		{/if}
		{#if book.position_label}
			<div class="chapter">your bookmark — {book.position_label}</div>
		{/if}
		<div class="progress-wrap">
			<ProgressBar percent={book.percent} />
			<span class="pct">{book.percent}%</span>
		</div>
		<div class="actions">
			<button class="link-btn small-caps" onclick={() => onupdate(book)}>Update progress</button>
			<button class="link-btn small-caps brass" onclick={() => onask(book)}>Ask about this</button>
		</div>
	</div>
</div>

<style>
	.card {
		display: flex;
		gap: var(--sp-6);
		width: 100%;
		max-width: 460px;
	}
	.cover-col {
		flex-shrink: 0;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.meta-col {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		padding-top: var(--sp-2);
		flex: 1;
		min-width: 0;
	}
	.series-label {
		color: var(--bone-muted);
		font-size: 10px;
	}
	.title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-28);
		color: var(--bone);
		line-height: 1.2;
	}
	.author {
		font-family: var(--serif-body);
		font-size: var(--fs-16);
		color: var(--bone-muted);
	}
	.chapter {
		font-family: var(--serif-body);
		font-size: var(--fs-14);
		color: var(--bone-muted);
	}
	.progress-wrap {
		margin-top: var(--sp-2);
		display: flex;
		align-items: center;
		gap: var(--sp-3);
	}
	.progress-wrap :global(.track) {
		flex: 1;
	}
	.pct {
		font-family: var(--mono);
		font-size: var(--fs-13);
		color: var(--brass);
		flex-shrink: 0;
	}
	.actions {
		margin-top: auto;
		display: flex;
		gap: var(--sp-4);
		padding-top: var(--sp-3);
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
