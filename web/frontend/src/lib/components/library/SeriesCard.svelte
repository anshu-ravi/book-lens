<script lang="ts">
	import type { SeriesGroup } from '$lib/types';
	import { seriesName } from '$lib/utils/series-name';
	import BookCover from './BookCover.svelte';
	import ProgressBar from './ProgressBar.svelte';

	let {
		series,
		onopen,
	}: {
		series: SeriesGroup;
		onopen: () => void;
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
	<button class="card" onclick={onopen}>
		<div class="cover-row">
			<BookCover
				title={firstBook.title}
				author={firstBook.author}
				seriesId={series.id}
				positionInSeries={firstBook.book_order}
				size="small"
				coverUrl={firstBook.has_cover ? `/api/books/${firstBook.id}/cover` : null}
			/>
		</div>
		<div class="name">{seriesName(series.id)}</div>
		<div class="counts small-caps">
			{series.books.length} vol. · {finishedCount}/{series.books.length} finished
		</div>
		<ProgressBar {percent} />
	</button>
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
		cursor: pointer;
		text-align: left;
	}
	.cover-row {
		display: flex;
		justify-content: center;
	}
	.name {
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
		transition: color 0.15s;
	}
	.card:hover .name {
		color: var(--brass);
	}
	.counts {
		color: var(--bone-muted);
	}
</style>
