<script lang="ts">
	import { onMount } from 'svelte';
	import { getGoodreadsShelves, getGoodreadsBooks, syncGoodreads, ApiError } from '$lib/api';
	import type { GoodreadsShelf, GoodreadsBook } from '$lib/types';
	import { shelfLabel } from '$lib/utils/goodreads-shelf';
	import { formatRelative } from '$lib/utils/format-date';
	import GoodreadsBookModal from '$lib/components/goodreads/GoodreadsBookModal.svelte';
	import GoodreadsCover from '$lib/components/goodreads/GoodreadsCover.svelte';

	let shelves = $state<GoodreadsShelf[]>([]);
	let syncedAt = $state<string | null>(null);
	let selectedShelf = $state<string>('all');
	let books = $state<GoodreadsBook[]>([]);

	let loadingShelves = $state(true);
	let loadingBooks = $state(false);
	let error = $state('');
	let neverSynced = $state(false);
	let syncing = $state(false);

	let activeBook = $state<GoodreadsBook | null>(null);

	async function loadShelves() {
		loadingShelves = true;
		error = '';
		neverSynced = false;
		try {
			const res = await getGoodreadsShelves();
			shelves = res.shelves;
			syncedAt = res.synced_at;
			if (res.synced_at === null && res.total === 0) neverSynced = true;
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not reach the Goodreads cache.';
		} finally {
			loadingShelves = false;
		}
	}

	async function loadBooks(shelf: string) {
		loadingBooks = true;
		error = '';
		try {
			const res = await getGoodreadsBooks(shelf);
			books = res.books;
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not load books for this shelf.';
			books = [];
		} finally {
			loadingBooks = false;
		}
	}

	function selectShelf(shelf: string) {
		selectedShelf = shelf;
		loadBooks(shelf);
	}

	async function refresh() {
		syncing = true;
		error = '';
		try {
			await syncGoodreads();
			await loadShelves();
			await loadBooks(selectedShelf);
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not sync from Goodreads.';
		} finally {
			syncing = false;
		}
	}

	onMount(async () => {
		await loadShelves();
		if (!neverSynced) await loadBooks(selectedShelf);
	});

</script>

<svelte:head>
	<title>BookLens · Goodreads</title>
</svelte:head>

<div class="greeting-strip">
	<span class="small-caps meta-line">Your Goodreads shelves</span>
	<h1 class="display-line">What you've logged</h1>
</div>

{#if loadingShelves}
	<p class="loading-text">Opening the shelves…</p>
{:else if error && shelves.length === 0}
	<p class="error-text">{error}</p>
{:else if neverSynced}
	<div class="empty-state">
		<p>Nothing synced yet.</p>
		<button type="button" class="small-caps sync-link" onclick={refresh} disabled={syncing}>
			{syncing ? 'Syncing…' : 'Sync from Goodreads →'}
		</button>
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
					<span class="shelf-count">{shelves.reduce((n, s) => n + s.count, 0)}</span>
				</button>
				{#each shelves as s (s.shelf)}
					<button
						type="button"
						class="shelf-row"
						class:active={selectedShelf === s.shelf}
						onclick={() => selectShelf(s.shelf)}
					>
						<span class="small-caps shelf-name">{shelfLabel(s.shelf)}</span>
						<span class="shelf-count">{s.count}</span>
					</button>
					{#if s.truncated}
						<p class="truncated-warning">
							{shelfLabel(s.shelf)} hit Goodreads' 100-item feed cap and may be incomplete.
						</p>
					{/if}
				{/each}
			</nav>

			<div class="rail-rule"></div>

			<button type="button" class="refresh-btn small-caps" onclick={refresh} disabled={syncing}>
				{syncing ? 'Syncing…' : 'Refresh from Goodreads'}
			</button>
			{#if syncedAt}
				<p class="synced-at">Last synced {formatRelative(syncedAt)}</p>
			{/if}
		</aside>

		<main class="grid-area">
			{#if error}
				<p class="error-text">{error}</p>
			{:else if loadingBooks}
				<p class="loading-text">Loading covers…</p>
			{:else if books.length === 0}
				<p class="loading-text">No books on this shelf.</p>
			{:else}
				<div class="cover-grid">
					{#each books as book (book.review_id)}
						<GoodreadsCover {book} onopen={() => (activeBook = book)} />
					{/each}
				</div>
			{/if}
		</main>
	</div>
{/if}

{#if activeBook}
	<GoodreadsBookModal book={activeBook} onclose={() => (activeBook = null)} />
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
	}
	.empty-state p {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone-muted);
		margin: 0;
	}
	.sync-link {
		background: none;
		border: none;
		padding: 0;
		color: var(--brass);
		cursor: pointer;
	}
	.sync-link:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.greeting-strip {
		margin-bottom: var(--sp-12);
	}
	.meta-line {
		color: var(--brass);
		display: block;
		margin-bottom: var(--sp-2);
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
		grid-template-columns: 220px 1fr;
		gap: var(--sp-8);
		align-items: start;
	}
	.rail {
		display: flex;
		flex-direction: column;
		position: sticky;
		top: calc(var(--header-h) + var(--sp-4));
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
	.truncated-warning {
		font-size: var(--fs-12);
		color: var(--oxblood);
		margin: 0 0 var(--sp-2) var(--sp-3);
		padding-right: var(--sp-2);
		line-height: 1.4;
	}
	.rail-rule {
		height: 1px;
		background: var(--ink-hairline);
		margin: var(--sp-4) var(--sp-3);
	}
	.refresh-btn {
		background: none;
		border: var(--hairline);
		border-radius: var(--r-chip);
		padding: var(--sp-2) var(--sp-3);
		margin: 0 var(--sp-3);
		color: var(--brass);
		cursor: pointer;
		transition: border-color 0.15s;
	}
	.refresh-btn:hover {
		border-color: var(--brass);
	}
	.refresh-btn:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.synced-at {
		font-size: var(--fs-12);
		color: var(--bone-faint);
		margin: var(--sp-2) var(--sp-3) 0;
	}
	.grid-area {
		min-width: 0;
	}
	.cover-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
		gap: var(--sp-6) var(--sp-4);
		align-items: end;
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
