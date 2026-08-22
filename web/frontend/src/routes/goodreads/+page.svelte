<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getGoodreadsShelves,
		getGoodreadsBooks,
		getGoodreadsSettings,
		syncGoodreads,
		ApiError,
	} from '$lib/api';
	import type { GoodreadsShelf, GoodreadsBook, GoodreadsSettingsResponse } from '$lib/types';
	import { shelfLabel } from '$lib/utils/goodreads-shelf';
	import { formatRelative } from '$lib/utils/format-date';
	import GoodreadsBookModal from '$lib/components/goodreads/GoodreadsBookModal.svelte';
	import GoodreadsCover from '$lib/components/goodreads/GoodreadsCover.svelte';
	import GoodreadsSettingsForm from '$lib/components/goodreads/GoodreadsSettingsForm.svelte';

	let shelves = $state<GoodreadsShelf[]>([]);
	let syncedAt = $state<string | null>(null);
	let selectedShelf = $state<string>('all');
	let books = $state<GoodreadsBook[]>([]);
	let settings = $state<GoodreadsSettingsResponse | null>(null);

	let loadingShelves = $state(true);
	let loadingBooks = $state(false);
	// A load error means the local cache itself couldn't be read -- there is
	// genuinely nothing to show. A sync error means a refresh attempt failed
	// while good cached data is still sitting in `shelves`/`books`; it must
	// never blank that out.
	let loadError = $state('');
	let syncError = $state('');
	let neverSynced = $state(false);
	let syncing = $state(false);
	let showSettingsForm = $state(false);

	let activeBook = $state<GoodreadsBook | null>(null);

	async function loadSettings() {
		try {
			settings = await getGoodreadsSettings();
		} catch {
			// Non-fatal: a stale id badge is fine, and refresh() surfaces
			// any real problem the next time it's used.
		}
	}

	async function loadShelves() {
		loadingShelves = true;
		loadError = '';
		neverSynced = false;
		try {
			const res = await getGoodreadsShelves();
			shelves = res.shelves;
			syncedAt = res.synced_at;
			if (res.synced_at === null && res.total === 0) neverSynced = true;
		} catch (e) {
			loadError = e instanceof ApiError ? e.detail : 'Could not reach the Goodreads cache.';
		} finally {
			loadingShelves = false;
		}
	}

	async function loadBooks(shelf: string) {
		loadingBooks = true;
		loadError = '';
		try {
			const res = await getGoodreadsBooks(shelf);
			books = res.books;
		} catch (e) {
			loadError = e instanceof ApiError ? e.detail : 'Could not load books for this shelf.';
			books = [];
		} finally {
			loadingBooks = false;
		}
	}

	function selectShelf(shelf: string) {
		selectedShelf = shelf;
		syncError = '';
		loadBooks(shelf);
	}

	async function refresh() {
		if (!settings?.user_id) {
			showSettingsForm = true;
			return;
		}
		syncError = '';
		syncing = true;
		try {
			await syncGoodreads();
			await loadShelves();
			await loadBooks(selectedShelf);
		} catch (e) {
			syncError = e instanceof ApiError ? e.detail : 'Could not sync from Goodreads.';
		} finally {
			syncing = false;
		}
	}

	async function handleSettingsSaved(saved: GoodreadsSettingsResponse) {
		settings = saved;
		showSettingsForm = false;
		await refresh();
	}

	onMount(async () => {
		await Promise.all([loadSettings(), loadShelves()]);
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
{:else if loadError && shelves.length === 0}
	<p class="error-text">{loadError}</p>
{:else if neverSynced}
	<div class="empty-state">
		<p>Nothing synced yet.</p>
		{#if settings?.user_id && !showSettingsForm}
			<button type="button" class="small-caps sync-link" onclick={refresh} disabled={syncing}>
				{syncing ? 'Syncing…' : 'Sync from Goodreads →'}
			</button>
		{:else}
			<GoodreadsSettingsForm
				initialUserId={settings?.user_id ?? ''}
				initialDnfShelf={settings?.dnf_shelf ?? ''}
				onSave={handleSettingsSaved}
			/>
		{/if}
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
			{#if settings?.user_id}
				<p class="settings-line">
					<span class="small-caps">id</span>
					<span class="user-id">{settings.user_id}</span>
					<button
						type="button"
						class="change-btn small-caps"
						onclick={() => (showSettingsForm = !showSettingsForm)}
					>
						change
					</button>
				</p>
			{:else}
				<p class="settings-line">
					<button
						type="button"
						class="change-btn small-caps"
						onclick={() => (showSettingsForm = !showSettingsForm)}
					>
						set Goodreads id
					</button>
				</p>
			{/if}
			{#if showSettingsForm}
				<GoodreadsSettingsForm
					initialUserId={settings?.user_id ?? ''}
					initialDnfShelf={settings?.dnf_shelf ?? ''}
					onSave={handleSettingsSaved}
					onCancel={() => (showSettingsForm = false)}
				/>
			{/if}
		</aside>

		<main class="grid-area">
			{#if syncError}
				<div class="sync-banner" role="alert">
					<span>{syncError}</span>
					<button
						type="button"
						class="dismiss-btn"
						onclick={() => (syncError = '')}
						aria-label="Dismiss"
					>
						×
					</button>
				</div>
			{/if}
			{#if loadError}
				<p class="error-text">{loadError}</p>
			{:else if loadingBooks}
				<p class="loading-text">Loading covers…</p>
			{:else if books.length === 0}
				<p class="loading-text">No books on this shelf.</p>
			{:else}
				<div class="cover-grid">
					{#each books as book (book.review_id)}
						<GoodreadsCover
							{book}
							onopen={() => (activeBook = book)}
							showReadTag={selectedShelf === 'all' && book.shelf === 'read'}
						/>
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
		max-width: 360px;
	}
	.empty-state p {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone-muted);
		margin: 0;
	}
	.empty-state :global(.settings-form) {
		width: 100%;
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
	.settings-line {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		font-size: var(--fs-12);
		color: var(--bone-faint);
		margin: var(--sp-2) var(--sp-3) 0;
	}
	.user-id {
		font-family: var(--mono);
		color: var(--bone-muted);
	}
	.change-btn {
		background: none;
		border: none;
		padding: 0;
		color: var(--brass);
		cursor: pointer;
		font-size: var(--fs-12);
	}
	.rail :global(.settings-form) {
		margin: var(--sp-3) var(--sp-3) 0;
	}
	.grid-area {
		min-width: 0;
	}
	.sync-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-3);
		border: 1px solid var(--oxblood);
		border-radius: var(--r-chip);
		padding: var(--sp-2) var(--sp-3);
		margin-bottom: var(--sp-4);
		color: var(--oxblood);
		font-size: var(--fs-13);
	}
	.dismiss-btn {
		background: none;
		border: none;
		padding: 0 var(--sp-1);
		color: var(--oxblood);
		cursor: pointer;
		font-size: var(--fs-16);
		line-height: 1;
	}
	.cover-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
		gap: var(--sp-6) var(--sp-4);
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
