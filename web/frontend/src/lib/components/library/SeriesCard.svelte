<script lang="ts">
	import type { BookStatus, SeriesGroup } from '$lib/types';
	import { seriesName } from '$lib/utils/series-name';
	import BookCover from './BookCover.svelte';
	import StateChip from './StateChip.svelte';

	let {
		series,
		onopen,
	}: {
		series: SeriesGroup;
		onopen: () => void;
	} = $props();

	const sorted = $derived([...series.books].sort((a, b) => a.book_order - b.book_order));
	const firstBook = $derived(sorted[0]);
	const seriesStatus = $derived.by<BookStatus>(() => {
		if (series.books.every((b) => b.status === 'finished')) return 'finished';
		const inProgress = series.books.some(
			(b) => b.status === 'finished' || b.status === 'reading' || b.chapters_read > 0,
		);
		return inProgress ? 'reading' : 'unread';
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
				coverUrl={firstBook.has_cover ? `/api/books/${firstBook.id}/cover` : null}
				fill
			/>
			<StateChip status={seriesStatus} overlay />
		</div>
		<div class="name">{seriesName(series.id)}</div>
	</button>
</div>

<style>
	.card {
		width: 200px;
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
		position: relative;
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
</style>
