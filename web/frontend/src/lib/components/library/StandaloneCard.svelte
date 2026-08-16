<script lang="ts">
	import type { Book, SeriesGroup } from '$lib/types';
	import BookCover from './BookCover.svelte';
	import ProgressBar from './ProgressBar.svelte';
	import StateChip from './StateChip.svelte';

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
</script>

<div class="carousel-item">
	<div class="card">
		<BookCover
			title={book.title}
			author={book.author}
			seriesId={series.id}
			size="medium"
			coverUrl={book.has_cover ? `/api/books/${book.id}/cover` : null}
		/>
		<div class="meta">
			<div class="title">{book.title}</div>
			{#if book.author}
				<div class="author">by {book.author}</div>
			{/if}
			<StateChip status={book.status} />
			<div class="progress-wrap">
				<ProgressBar percent={book.percent} />
				<span class="pct mono">{book.percent}%</span>
			</div>
			<div class="actions">
				<button class="link-btn small-caps" onclick={() => onupdate(book)}>Update progress</button>
				<button class="link-btn small-caps brass" onclick={() => onask(book)}>Ask about this</button>
			</div>
		</div>
	</div>
</div>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		width: 160px;
	}
	.meta {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		align-items: flex-start;
	}
	.title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone);
		line-height: 1.25;
	}
	.author {
		font-family: var(--serif-body);
		font-size: var(--fs-14);
		color: var(--bone-muted);
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
