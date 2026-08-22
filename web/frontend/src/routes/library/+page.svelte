<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { getUnifiedLibrary, getLibrary, ApiError } from '$lib/api';
	import type { Book, UnifiedEntry, UnifiedShelf } from '$lib/types';
	import BookCard from '$lib/components/library/BookCard.svelte';
	import BookModal from '$lib/components/library/BookModal.svelte';
	import BookEditModal from '$lib/components/library/BookEditModal.svelte';

	let shelves = $state<UnifiedShelf[]>([]);
	let totals = $state({ books: 0, with_epub: 0, askable: 0 });
	let libraryByBookId = $state<Map<string, { book: Book; seriesId: string }>>(new Map());

	let loading = $state(true);
	// A load error means the library itself couldn't be read -- there is
	// genuinely nothing to show.
	let loadError = $state('');

	let openEntry = $state<UnifiedEntry | null>(null);
	let openTrigger: HTMLElement | null = null;
	let editing = $state<{ entry: UnifiedEntry; focus: 'details' | 'reading' } | null>(null);

	const requestedShelf = $derived($page.url.searchParams.get('shelf') ?? 'all');
	const selectedShelf = $derived(
		requestedShelf === 'all' || shelves.some((s) => s.shelf === requestedShelf)
			? requestedShelf
			: 'all',
	);

	async function load() {
		loading = true;
		loadError = '';
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
			loadError = e instanceof ApiError ? e.detail : 'Could not load the library.';
		} finally {
			loading = false;
		}
	}

	function selectShelf(shelf: string) {
		const params = new URLSearchParams($page.url.searchParams);
		if (shelf === 'all') params.delete('shelf');
		else params.set('shelf', shelf);
		const qs = params.toString();
		goto(`/library${qs ? `?${qs}` : ''}`, { replaceState: true, noScroll: true, keepFocus: true });
	}

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

	onMount(async () => {
		await load();
	});

	/** Flattens a shelf's groups in the order the backend already sorted them -- never re-sorted here. */
	function flatten(shelf: UnifiedShelf): { entry: UnifiedEntry; inSeriesRun: boolean }[] {
		return shelf.groups.flatMap((g) =>
			g.books.map((entry) => ({ entry, inSeriesRun: g.books.length > 1 })),
		);
	}

	const activeShelves = $derived(
		selectedShelf === 'all' ? shelves : shelves.filter((s) => s.shelf === selectedShelf),
	);
</script>

<svelte:head>
	<title>BookLens · Library</title>
</svelte:head>

<div class="greeting-strip">
	<h1 class="display-line">Your library</h1>
</div>

{#if loading}
	<p class="loading-text">Opening the shelves…</p>
{:else if loadError}
	<p class="error-text">{loadError}</p>
{:else if totals.books === 0}
	<div class="empty-state">
		<p>Nothing on the shelves yet.</p>
		<a href="/upload" class="small-caps">Add a volume →</a>
	</div>
{:else}
	<div class="layout">
		<aside class="rail">
			<nav class="shelf-list">
				<button
					type="button"
					class="shelf-row"
					class:active={selectedShelf === 'all'}
					onclick={() => selectShelf('all')}
				>
					<span class="small-caps shelf-name">All</span>
					<span class="shelf-count">{totals.books}</span>
				</button>
				{#each shelves as s (s.shelf)}
					<button
						type="button"
						class="shelf-row"
						class:active={selectedShelf === s.shelf}
						onclick={() => selectShelf(s.shelf)}
					>
						<span class="small-caps shelf-name">{s.label}</span>
						<span class="shelf-count">{s.count}</span>
					</button>
				{/each}
			</nav>
		</aside>

		<main class="grid-area">
			{#if activeShelves.every((s) => s.count === 0)}
				<p class="loading-text">No books on this shelf.</p>
			{:else if selectedShelf === 'all'}
				{#each shelves as shelf (shelf.shelf)}
					{#if shelf.count > 0}
						<section class="shelf-section">
							<h2 class="small-caps section-hd">{shelf.label}</h2>
							<div class="cover-grid">
								{#each flatten(shelf) as { entry, inSeriesRun } (entry.book_id ?? entry.goodreads_book_id)}
									<BookCard {entry} {inSeriesRun} onopen={() => openBook(entry)} />
								{/each}
							</div>
						</section>
					{/if}
				{/each}
			{:else}
				{#each activeShelves as shelf (shelf.shelf)}
					<div class="cover-grid">
						{#each flatten(shelf) as { entry, inSeriesRun } (entry.book_id ?? entry.goodreads_book_id)}
							<BookCard {entry} {inSeriesRun} onopen={() => openBook(entry)} />
						{/each}
					</div>
				{/each}
			{/if}
		</main>
	</div>
{/if}

{#if openEntry}
	<BookModal
		entry={openEntry}
		onclose={closeBook}
		onedit={(focus) => openEdit(openEntry!, focus)}
		escapeEnabled={editing === null}
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
	.error-text {
		color: var(--oxblood);
	}
	.empty-state {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		align-items: flex-start;
		padding: var(--sp-16) 0;
		max-width: 360px;
	}
	.empty-state p {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone-muted);
		margin: 0;
	}
	.empty-state a {
		color: var(--brass);
		text-decoration: none;
	}
	.greeting-strip {
		margin-bottom: var(--sp-12);
	}
	.display-line {
		font-family: var(--serif-display);
		font-style: italic;
		font-weight: 400;
		font-size: var(--fs-40);
		color: var(--bone);
		margin: 0;
	}
	.layout {
		display: grid;
		grid-template-columns: 220px minmax(0, 1fr);
		gap: var(--sp-8);
		align-items: start;
	}
	.rail {
		display: flex;
		flex-direction: column;
		position: sticky;
		top: var(--sp-4);
	}
	.shelf-list {
		display: flex;
		flex-direction: column;
	}
	.shelf-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-2);
		background: none;
		border: none;
		border-left: 2px solid transparent;
		padding: var(--sp-2) var(--sp-3);
		cursor: pointer;
		text-align: left;
		color: var(--bone-muted);
		transition: color 0.15s, border-color 0.15s;
	}
	.shelf-row:hover {
		color: var(--bone);
	}
	.shelf-row.active {
		color: var(--brass);
		border-left-color: var(--brass);
	}
	.shelf-name {
		flex: 1;
	}
	.shelf-count {
		font-family: var(--mono);
		font-size: var(--fs-12);
		color: var(--bone-faint);
	}
	.grid-area {
		min-width: 0;
	}
	.shelf-section {
		margin-bottom: var(--sp-12);
	}
	.section-hd {
		color: var(--bone-muted);
		display: block;
		margin: 0 0 var(--sp-4);
	}
	.cover-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
		gap: var(--sp-6);
		align-items: stretch;
	}
	@media (max-width: 900px) {
		.layout {
			grid-template-columns: 1fr;
		}
		.rail {
			position: static;
		}
	}
</style>
