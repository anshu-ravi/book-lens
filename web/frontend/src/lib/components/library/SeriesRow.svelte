<script lang="ts">
	import type { Book, SeriesGroup } from '$lib/types';
	import DottedLeader from './DottedLeader.svelte';
	import StateChip from './StateChip.svelte';
	import BookCover from './BookCover.svelte';
	import { seriesName } from '$lib/utils/series-name';

	let {
		series,
		expanded,
		ontoggle,
		onbookclick,
	}: {
		series: SeriesGroup;
		expanded: boolean;
		ontoggle: () => void;
		onbookclick: (book: Book) => void;
	} = $props();

	const readCount = $derived(series.books.filter((b) => b.status === 'finished').length);
	const sorted = $derived([...series.books].sort((a, b) => a.book_order - b.book_order));
</script>

<div class="series-wrap">
	<button class="row" onclick={ontoggle} aria-expanded={expanded}>
		<span class="series-name">{seriesName(series.id)}</span>
		<DottedLeader />
		<span class="vols small-caps">{series.books.length} vol.</span>
		<span class="read-chip small-caps">{readCount}/{series.books.length} read</span>
	</button>

	{#if expanded}
		<table class="book-table">
			<tbody>
				{#each sorted as book (book.id)}
					<tr>
						<td class="order mono">{book.book_order}</td>
						<td class="thumb-cell">
							<BookCover
								title={book.title}
								author={book.author}
								seriesId={series.id}
								positionInSeries={book.book_order}
								size="thumb"
								coverUrl={book.has_cover ? `/api/books/${book.id}/cover` : null}
							/>
						</td>
						<td class="title-cell">
							<button class="title-btn" onclick={() => onbookclick(book)}>{book.title}</button>
						</td>
						<td><StateChip status={book.status} /></td>
						<td class="pct mono">{book.percent}%</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.series-wrap {
		border-bottom: var(--hairline);
	}
	.row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-3) 0;
		border: none;
		background: none;
		cursor: pointer;
		text-align: left;
	}
	.row:hover .series-name {
		color: var(--brass);
	}
	.series-name {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone);
		white-space: nowrap;
		transition: color 0.15s;
	}
	.vols,
	.read-chip {
		color: var(--bone-muted);
		white-space: nowrap;
		flex-shrink: 0;
	}
	.book-table {
		width: 100%;
		border-collapse: collapse;
		margin-bottom: var(--sp-4);
	}
	.book-table td {
		padding: var(--sp-2) var(--sp-2);
		border-top: 1px solid var(--ink-hairline);
		font-size: var(--fs-14);
	}
	.order {
		color: var(--bone-muted);
		width: 2.5em;
	}
	.thumb-cell {
		width: 34px;
		padding-right: var(--sp-3);
	}
	.title-cell {
		width: 60%;
	}
	.title-btn {
		background: none;
		border: none;
		color: var(--bone);
		font-family: var(--serif-body);
		cursor: pointer;
		padding: 0;
		text-align: left;
		text-decoration: underline;
		text-underline-offset: 3px;
		text-decoration-color: transparent;
		transition: text-decoration-color 0.15s;
	}
	.title-btn:hover {
		text-decoration-color: var(--brass);
	}
	.pct {
		color: var(--brass);
		text-align: right;
	}
</style>
