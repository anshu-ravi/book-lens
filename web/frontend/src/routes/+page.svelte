<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { getUnifiedLibrary, getLibrary, ApiError } from '$lib/api';
	import type { Book, UnifiedEntry, UnifiedShelf } from '$lib/types';
	import ReadingCard from '$lib/components/library/ReadingCard.svelte';
	import Shelf from '$lib/components/library/Shelf.svelte';
	import BookModal from '$lib/components/library/BookModal.svelte';
	import BookEditModal from '$lib/components/library/BookEditModal.svelte';

	let shelves = $state<UnifiedShelf[]>([]);
	let totals = $state({ books: 0, with_epub: 0, askable: 0 });
	// Keyed by book_id -- joined in purely to get percent/chapters_read for the
	// reading cards, since the unified entry itself carries neither.
	let libraryByBookId = $state<Map<string, { book: Book; seriesId: string }>>(new Map());
	let loading = $state(true);
	let error = $state('');
	let query = $state('');

	let openEntry = $state<UnifiedEntry | null>(null);
	let openTrigger: HTMLElement | null = null;
	let editing = $state<{ entry: UnifiedEntry; focus: 'details' | 'reading' } | null>(null);

	async function load() {
		loading = true;
		error = '';
		try {
			const [unified, library] = await Promise.all([getUnifiedLibrary(), getLibrary()]);
			shelves = unified.shelves;
			totals = unified.totals;
			const map = new Map<string, { book: Book; seriesId: string }>();
			for (const s of library.series) {
				for (const b of s.books) map.set(b.id, { book: b, seriesId: s.id });
			}
			libraryByBookId = map;
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not load the library.';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	const readingShelf = $derived(shelves.find((s) => s.shelf === 'reading') ?? null);
	const otherShelves = $derived(shelves.filter((s) => s.shelf !== 'reading'));

	function matches(entry: UnifiedEntry, q: string): boolean {
		const needle = q.trim().toLowerCase();
		if (!needle) return true;
		return entry.title.toLowerCase().includes(needle) || entry.author.toLowerCase().includes(needle);
	}

	function filterShelf(shelf: UnifiedShelf, q: string): UnifiedShelf {
		if (!q.trim()) return shelf;
		const groups = shelf.groups
			.map((g) => ({ ...g, books: g.books.filter((b) => matches(b, q)) }))
			.filter((g) => g.books.length > 0);
		return { ...shelf, groups, count: groups.reduce((n, g) => n + g.books.length, 0) };
	}

	const filteredReadingShelf = $derived(readingShelf ? filterShelf(readingShelf, query) : null);
	const filteredOtherShelves = $derived(otherShelves.map((s) => filterShelf(s, query)));

	function openBook(entry: UnifiedEntry, trigger?: HTMLElement) {
		openTrigger = trigger ?? (document.activeElement as HTMLElement | null);
		openEntry = entry;
	}

	function closeBook() {
		openEntry = null;
		openTrigger?.focus();
		openTrigger = null;
	}

	function openEdit(entry: UnifiedEntry, focus: 'details' | 'reading') {
		editing = { entry, focus };
	}

	function closeEdit() {
		editing = null;
	}

	async function onSaved() {
		editing = null;
		openEntry = null;
		await load();
	}

	function askAbout(bookId: string) {
		goto(`/chat?book=${encodeURIComponent(bookId)}`);
	}
</script>

<svelte:head>
	<title>BookLens · Library</title>
</svelte:head>

{#if loading}
	<p class="loading-text">Opening the index…</p>
{:else if error}
	<p class="error-text">{error}</p>
{:else}
	<div class="bar">
		<div class="greet">
			<span class="small-caps meta">{totals.books} books · {totals.with_epub} you can ask about</span>
			<h1 class="display-line">Where were we?</h1>
		</div>
		<label class="find">
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
				<circle cx="11" cy="11" r="7" />
				<path d="m20 20-3.6-3.6" />
			</svg>
			<input placeholder="Search in my library" bind:value={query} />
		</label>
	</div>

	{#if filteredReadingShelf && filteredReadingShelf.groups.length > 0}
		<section class="row">
			<div class="row-hd">
				<h2>Currently reading</h2>
				<span class="ct">{filteredReadingShelf.count}</span>
			</div>
			<div class="rc-row">
				{#each filteredReadingShelf.groups as group (group.series ?? group.books[0].book_id ?? group.books[0].goodreads_book_id)}
					{#each group.books as entry (entry.book_id ?? entry.goodreads_book_id)}
						{@const joined = entry.book_id ? libraryByBookId.get(entry.book_id) : undefined}
						<ReadingCard
							{entry}
							percent={joined ? joined.book.percent : null}
							chaptersRead={joined ? joined.book.chapters_read : null}
							onopen={() => openBook(entry)}
							onedit={() => openEdit(entry, 'reading')}
							onask={() => entry.book_id && askAbout(entry.book_id)}
						/>
					{/each}
				{/each}
			</div>
		</section>
	{/if}

	{#each filteredOtherShelves as shelf (shelf.shelf)}
		{#if shelf.groups.length > 0}
			<Shelf {shelf} onopen={(entry) => openBook(entry)} />
		{/if}
	{/each}

	{#if totals.books === 0}
		<div class="empty-state">
			<p>Nothing on the shelves yet.</p>
			<a href="/upload" class="small-caps">Add a volume →</a>
		</div>
	{/if}
{/if}

{#if openEntry}
	<BookModal
		entry={openEntry}
		onclose={closeBook}
		onedit={(focus) => openEdit(openEntry!, focus)}
	/>
{/if}

{#if editing}
	{#if editing.entry.book_id && libraryByBookId.get(editing.entry.book_id)}
		{@const joined = libraryByBookId.get(editing.entry.book_id)!}
		<BookEditModal
			book={joined.book}
			seriesId={joined.seriesId}
			focus={editing.focus}
			onclose={closeEdit}
			onsaved={onSaved}
		/>
	{/if}
{/if}

<style>
	.loading-text,
	.error-text {
		font-style: italic;
		color: var(--bone-muted);
	}
	.empty-state {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		align-items: flex-start;
		padding: var(--sp-16) 0;
	}
	.empty-state p {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone-muted);
	}
	.empty-state a {
		color: var(--brass);
		text-decoration: none;
	}
	.bar {
		display: flex;
		align-items: flex-end;
		gap: var(--sp-4);
		margin-bottom: var(--sp-12);
		flex-wrap: wrap;
	}
	.meta {
		color: var(--brass-text);
		display: block;
		margin-bottom: var(--sp-2);
	}
	.display-line {
		font-family: var(--serif-display);
		font-style: italic;
		font-weight: 400;
		font-size: var(--fs-40);
		margin: 0;
		line-height: 1;
		color: var(--bone);
	}
	.find {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		margin-left: auto;
		width: 280px;
		background: var(--ink-bg);
		border: var(--hairline);
		border-radius: var(--r-chip);
		padding: 9px var(--sp-3);
		color: var(--bone-faint);
	}
	.find svg {
		width: 17px;
		height: 17px;
		flex: 0 0 auto;
	}
	.find input {
		font-family: var(--sans-caps);
		font-size: var(--fs-13);
		color: var(--bone);
		background: none;
		border: none;
		outline: none;
		width: 100%;
	}
	.find input::placeholder {
		color: var(--bone-faint);
	}
	.row {
		margin-bottom: var(--sp-12);
	}
	.row-hd {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		margin-bottom: var(--sp-4);
	}
	.row-hd h2 {
		font-family: var(--sans-caps);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		font-size: var(--fs-12);
		font-weight: 400;
		color: var(--bone);
		margin: 0;
	}
	.ct {
		font-family: var(--mono);
		font-size: var(--fs-12);
		color: var(--bone-faint);
	}
	:root[data-theme='light'] .ct {
		color: var(--bone-muted);
	}
	.rc-row {
		display: flex;
		gap: var(--sp-6);
		flex-wrap: wrap;
	}
	@media (max-width: 900px) {
		.find {
			margin-left: 0;
			width: 100%;
		}
	}
</style>
