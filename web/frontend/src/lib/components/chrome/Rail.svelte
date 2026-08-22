<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { getLibrary, getGoodreadsShelves, getGoodreadsSettings, syncGoodreads, ApiError } from '$lib/api';
	import type { Book, GoodreadsSettingsResponse } from '$lib/types';
	import { formatRelative } from '$lib/utils/format-date';
	import ThemeToggle from './ThemeToggle.svelte';
	import GoodreadsSettingsForm from '../goodreads/GoodreadsSettingsForm.svelte';

	const links = [
		{
			href: '/',
			label: 'Home',
			icon: 'M3 10.5 12 3l9 7.5M5.5 9.5V21h13V9.5',
		},
		{
			href: '/library',
			label: 'Library',
			icon: 'M4 4h5v16H4zM11 4h4v16h-4zM17.2 4.6l3.4.9-4 15.4-3.3-.9z',
		},
		{
			href: '/upload',
			label: 'Upload',
			icon: 'M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 17v3h16v-3',
		},
		{
			href: '/chat',
			label: 'Chat',
			icon: 'M21 12a8 8 0 0 1-8 8H7l-4 3v-4.6A8 8 0 0 1 11 4h2a8 8 0 0 1 8 8Z',
		},
		{
			href: '/stats',
			label: 'Stats',
			icon: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
		},
	];

	let reading = $state<Book | null>(null);
	let coverFailed = $state(false);

	let settings = $state<GoodreadsSettingsResponse | null>(null);
	let syncedAt = $state<string | null>(null);
	let syncing = $state(false);
	let syncError = $state('');
	let showSettingsForm = $state(false);

	async function refresh() {
		if (!settings?.user_id) {
			showSettingsForm = true;
			return;
		}
		syncError = '';
		syncing = true;
		try {
			await syncGoodreads();
			// A client-side nav won't refetch page data (it's all loaded in onMount),
			// so force a full reload to bring the newly synced library into view.
			location.reload();
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
		try {
			const res = await getLibrary();
			for (const s of res.series) {
				const found = s.books.find((b) => b.status === 'reading');
				if (found) {
					reading = found;
					break;
				}
			}
		} catch {
			// The rail's "continue reading" card is a convenience, not load-bearing --
			// a failed fetch just means the card stays hidden.
		}

		try {
			settings = await getGoodreadsSettings();
		} catch {
			// Non-fatal: a stale id badge is fine, and refresh() surfaces
			// any real problem the next time it's used.
		}
		try {
			const goodreadsShelves = await getGoodreadsShelves();
			syncedAt = goodreadsShelves.synced_at;
		} catch {
			// Non-fatal: "last synced" just stays hidden.
		}
	});
</script>

<aside class="side">
	<div class="side-inner">
		<div class="mark">
			<div class="mark-t">
				<span class="brand">BookLens</span>
				<span class="tag">a reader's index</span>
			</div>
			<ThemeToggle />
		</div>

		<nav>
			{#each links as link (link.href)}
				<a href={link.href} class="nv" class:on={$page.url.pathname === link.href}>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
						{#each link.icon.split('|') as d}
							<path {d} />
						{/each}
					</svg>
					<span>{link.label}</span>
				</a>
			{/each}
		</nav>

		{#if reading}
			<div class="cont">
				<span class="small-caps cont-l">Continue reading</span>
				<div class="cont-b">
					<div class="bk-c">
						{#if reading.has_cover && !coverFailed}
							<img src={`/api/books/${reading.id}/cover`} alt="" loading="lazy" onerror={() => (coverFailed = true)} />
						{:else}
							<div class="fb"></div>
						{/if}
					</div>
					<div class="cont-t">
						<p>{reading.title}</p>
						<span>{reading.author}</span>
					</div>
				</div>
				<div class="cont-p"><span style="width:{reading.percent}%"></span></div>
				<span class="cont-pos">Chapter {reading.chapters_read} · {reading.percent}%</span>
			</div>
		{/if}

		<div class="gr-rule"></div>
		<div class="gr">
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
			{#if syncError}
				<p class="gr-error">{syncError}</p>
			{/if}
			{#if showSettingsForm}
				<GoodreadsSettingsForm
					initialUserId={settings?.user_id ?? ''}
					initialDnfShelf={settings?.dnf_shelf ?? ''}
					onSave={handleSettingsSaved}
					onCancel={() => (showSettingsForm = false)}
				/>
			{/if}
		</div>
	</div>
</aside>

<style>
	.side {
		background: var(--ink-bg);
		border-right: var(--hairline);
		align-self: stretch;
		border-radius: var(--r-box) 0 0 var(--r-box);
	}
	.side-inner {
		padding: var(--sp-6) var(--sp-4);
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
		position: sticky;
		top: 0;
		max-height: 100vh;
		overflow-y: auto;
		scrollbar-width: none;
	}
	.side-inner::-webkit-scrollbar {
		display: none;
	}
	.mark {
		padding: 0 var(--sp-3);
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-3);
	}
	.mark-t {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.brand {
		font-family: var(--serif-display);
		font-size: var(--fs-22);
		color: var(--bone);
	}
	.tag {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--bone-muted);
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.nv {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: 9px var(--sp-3);
		border-radius: var(--r-chip);
		font-family: var(--sans-caps);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		font-size: var(--fs-12);
		color: var(--bone-muted);
		border-left: 2px solid transparent;
		text-decoration: none;
		transition: color 0.15s, background 0.15s, border-color 0.15s;
	}
	.nv svg {
		width: 17px;
		height: 17px;
		flex: 0 0 auto;
	}
	.nv:hover {
		color: var(--bone);
		background: var(--ink-surface);
	}
	.nv.on {
		color: var(--brass-text);
		border-left-color: var(--brass);
		background: var(--ink-surface);
	}
	.cont {
		border: var(--hairline);
		border-radius: var(--r-chip);
		padding: var(--sp-3);
		background: var(--ink-surface);
	}
	.cont-l {
		color: var(--bone-faint);
		display: block;
		margin-bottom: var(--sp-3);
	}
	.cont-b {
		display: flex;
		gap: var(--sp-3);
		align-items: flex-start;
	}
	.cont-b .bk-c {
		width: 44px;
		height: 66px;
		border-radius: 1px var(--r-cover) var(--r-cover) 1px;
		overflow: hidden;
		flex: 0 0 auto;
		box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4);
	}
	.bk-c img,
	.fb {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.fb {
		background: var(--ink-surface);
	}
	.cont-t {
		min-width: 0;
	}
	.cont-t p {
		font-family: var(--serif-display);
		font-size: var(--fs-14);
		margin: 0 0 2px;
		line-height: 1.25;
	}
	.cont-t span {
		font-size: var(--fs-12);
		color: var(--bone-faint);
	}
	.cont-p {
		height: 2px;
		background: var(--ink-hairline);
		margin-top: var(--sp-3);
		overflow: hidden;
	}
	.cont-p span {
		display: block;
		height: 100%;
		background: var(--brass);
	}
	.cont-pos {
		display: block;
		margin-top: 6px;
		font-family: var(--mono);
		font-size: var(--fs-12);
		color: var(--bone-faint);
	}
	:root[data-theme='light'] .cont-pos {
		color: var(--bone-muted);
	}
	.gr-rule {
		height: 1px;
		background: var(--ink-hairline);
	}
	.gr {
		display: flex;
		flex-direction: column;
		padding: 0 var(--sp-3);
	}
	.refresh-btn {
		background: none;
		border: var(--hairline);
		border-radius: var(--r-chip);
		padding: var(--sp-2) var(--sp-3);
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
		margin: var(--sp-2) 0 0;
	}
	.settings-line {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		font-size: var(--fs-12);
		color: var(--bone-faint);
		margin: var(--sp-2) 0 0;
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
	.gr-error {
		font-size: var(--fs-12);
		color: var(--oxblood);
		margin: var(--sp-2) 0 0;
	}
	.gr :global(.settings-form) {
		margin: var(--sp-3) 0 0;
	}
	@media (max-width: 900px) {
		.side {
			border-right: none;
			border-bottom: var(--hairline);
			border-radius: var(--r-box) var(--r-box) 0 0;
		}
		.side-inner {
			position: static;
			max-height: none;
		}
	}
</style>
