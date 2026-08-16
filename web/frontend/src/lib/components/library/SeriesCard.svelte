<script lang="ts">
	import type { SeriesGroup } from '$lib/types';
	import { seriesName } from '$lib/utils/series-name';
	import BookCover from './BookCover.svelte';
	import ProgressBar from './ProgressBar.svelte';

	let {
		series,
		expanded,
		ontoggle,
	}: {
		series: SeriesGroup;
		expanded: boolean;
		ontoggle: () => void;
	} = $props();

	const sorted = $derived([...series.books].sort((a, b) => a.book_order - b.book_order));
	const firstBook = $derived(sorted[0]);
	const finishedCount = $derived(series.books.filter((b) => b.status === 'finished').length);
	const percent = $derived.by(() => {
		const totalChapters = series.books.reduce((n, b) => n + b.chapter_count, 0);
		const readChapters = series.books.reduce((n, b) => n + b.chapters_read, 0);
		return totalChapters > 0 ? Math.round((readChapters / totalChapters) * 100) : 0;
	});
</script>

<div class="carousel-item">
	<button class="card" class:expanded onclick={ontoggle} aria-expanded={expanded}>
		<BookCover
			title={firstBook.title}
			author={firstBook.author}
			seriesId={series.id}
			positionInSeries={firstBook.book_order}
			size="medium"
			coverUrl={firstBook.has_cover ? `/api/books/${firstBook.id}/cover` : null}
		/>
		<div class="meta">
			<div class="name">{seriesName(series.id)}</div>
			<div class="counts small-caps">
				{series.books.length} vol. · {finishedCount}/{series.books.length} finished
			</div>
			<ProgressBar {percent} />
		</div>
	</button>
</div>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		width: 160px;
		background: none;
		border: none;
		padding: 0 0 var(--sp-2);
		cursor: pointer;
		text-align: left;
		border-bottom: 2px solid transparent;
	}
	.card.expanded {
		border-bottom-color: var(--brass);
	}
	.meta {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.name {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone);
		line-height: 1.25;
		transition: color 0.15s;
	}
	.card:hover .name {
		color: var(--brass);
	}
	.counts {
		color: var(--bone-muted);
	}
</style>
