<script lang="ts">
	import { onMount } from 'svelte';
	import { getSeries, inspectUpload, inspectCoverUrl, commitUpload, ApiError } from '$lib/api';
	import type { SeriesSummary, InspectResponse, CommitResponse } from '$lib/types';
	import { slugify, seriesName } from '$lib/utils/series-name';
	import { toRoman } from '$lib/utils/roman';
	import DropZone from '$lib/components/upload/DropZone.svelte';
	import StepRail from '$lib/components/upload/StepRail.svelte';
	import BookCover from '$lib/components/library/BookCover.svelte';

	const NEW_SERIES = '__new__';

	let file = $state<File | null>(null);
	let inspecting = $state(false);
	let inspectError = $state('');
	let inspectResult = $state<InspectResponse | null>(null);

	let allSeries = $state<SeriesSummary[]>([]);

	let editing = $state(false);
	let title = $state('');
	let author = $state('');
	let selectedSeries = $state('');
	let newSeriesName = $state('');
	let bookOrder = $state(1);
	let standalone = $state(false);

	let committing = $state(false);
	let commitError = $state('');
	let commitResult = $state<CommitResponse | null>(null);

	const step = $derived<1 | 2 | 3>(committing || commitResult ? 3 : file ? 2 : 1);
	const isNewSeries = $derived(selectedSeries === NEW_SERIES);
	const standaloneSeriesId = $derived(
		slugify(title || file?.name.replace(/\.epub$/i, '') || 'book'),
	);
	const effectiveSeriesId = $derived(
		standalone ? standaloneSeriesId : isNewSeries ? slugify(newSeriesName.trim()) : selectedSeries,
	);
	const canShelve = $derived(!!inspectResult && (standalone || !!effectiveSeriesId));

	// The suggestion still holds only while the user hasn't picked a different
	// series in the edit dropdown -- that's when "matched · N prior volumes" applies.
	const suggestionStillActive = $derived(
		!!inspectResult && !standalone && selectedSeries === inspectResult.suggested_series_id,
	);
	const seriesDisplayName = $derived.by(() => {
		if (standalone) return 'Standalone';
		if (isNewSeries) return newSeriesName.trim() || '—';
		if (!selectedSeries) return '—';
		if (suggestionStillActive && inspectResult?.suggested_series_name) {
			return inspectResult.suggested_series_name;
		}
		return seriesName(selectedSeries);
	});

	onMount(async () => {
		try {
			allSeries = (await getSeries()).series;
		} catch {
			// non-fatal: "new series" still works without the list
		}
	});

	function fileSizeLabel(bytes: number): string {
		const mb = bytes / (1024 * 1024);
		return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
	}

	function shortSha(sha: string): string {
		return `${sha.slice(0, 4)}…${sha.slice(-4)}`;
	}

	async function onFile(f: File) {
		file = f;
		inspectError = '';
		inspectResult = null;
		editing = false;
		commitResult = null;
		commitError = '';
		inspecting = true;
		try {
			const res = await inspectUpload(f);
			inspectResult = res;
			title = res.title;
			author = res.author ?? '';
			selectedSeries = res.suggested_series_id ?? '';
			newSeriesName = '';
			bookOrder = res.suggested_book_order;
			standalone = false;
		} catch (e) {
			inspectError = e instanceof ApiError ? e.detail : 'Could not read this EPUB.';
		} finally {
			inspecting = false;
		}
	}

	async function shelve() {
		if (!inspectResult || !canShelve) return;
		commitError = '';
		committing = true;
		try {
			commitResult = await commitUpload({
				sha256: inspectResult.sha256,
				title: title.trim() || null,
				author: author.trim() || null,
				series_id: standalone ? standaloneSeriesId : effectiveSeriesId,
				book_order: standalone ? 1 : bookOrder,
				standalone,
			});
		} catch (e) {
			commitError = e instanceof ApiError ? e.detail : 'Could not shelve the volume.';
		} finally {
			committing = false;
		}
	}

	function reset() {
		file = null;
		inspectResult = null;
		inspectError = '';
		editing = false;
		commitResult = null;
		commitError = '';
		committing = false;
	}
</script>

<svelte:head>
	<title>BookLens · Upload</title>
</svelte:head>

<div class="upload-layout">
	<StepRail {step} />

	<div class="main-panel">
		{#if step === 1}
			<DropZone onfile={onFile} />
		{:else if step === 2 || step === 3}
			<h1 class="page-title">Catalog entry.</h1>

			{#if file}
				<p class="file-line mono">
					{file.name} · {fileSizeLabel(file.size)}{#if inspectResult}
						{' · '}sha {shortSha(inspectResult.sha256)}{/if}
				</p>
			{/if}

			{#if inspecting}
				<div class="waiting">
					<div class="waiting-bar"><div class="waiting-fill"></div></div>
					<p class="waiting-copy">Reading the file front to back — this takes a moment.</p>
				</div>
			{:else if inspectError}
				<p class="error" role="alert">{inspectError}</p>
				<button class="btn-ghost small-caps" onclick={reset}>Try another file</button>
			{:else if inspectResult}
				<div class="entry-body">
					<div class="cover-frame">
						<BookCover
							{title}
							{author}
							seriesId={effectiveSeriesId || 'unshelved'}
							size="plate"
							coverUrl={inspectResult.has_cover ? inspectCoverUrl(inspectResult.sha256) : null}
						/>
					</div>

					<table class="catalog-table">
						<tbody>
							<tr>
								<td class="label small-caps">Title</td>
								<td class="value">
									{#if editing}
										<input type="text" bind:value={title} disabled={committing} />
									{:else}
										{title}
									{/if}
								</td>
							</tr>
							<tr>
								<td class="label small-caps">Author</td>
								<td class="value">
									{#if editing}
										<input type="text" bind:value={author} disabled={committing} />
									{:else}
										{author || '—'}
									{/if}
								</td>
							</tr>
							<tr>
								<td class="label small-caps">Series</td>
								<td class="value">
									{#if editing}
										<fieldset class="inline-field" disabled={committing || standalone}>
											<select bind:value={selectedSeries}>
												<option value="" disabled>Choose a series…</option>
												{#if inspectResult.suggested_series_id && !allSeries.some((s) => s.id === inspectResult?.suggested_series_id)}
													<option value={inspectResult.suggested_series_id}>
														{inspectResult.suggested_series_name} (new)
													</option>
												{/if}
												{#each allSeries as s (s.id)}
													<option value={s.id}>{seriesName(s.id)}</option>
												{/each}
												<option value={NEW_SERIES}>＋ new series…</option>
											</select>
											{#if isNewSeries}
												<input
													type="text"
													class="new-series-input"
													placeholder="New series name"
													bind:value={newSeriesName}
												/>
											{/if}
										</fieldset>
									{:else}
										{seriesDisplayName}
										{#if suggestionStillActive && inspectResult.prior_volumes > 0}
											<span class="series-note italic">
												matched · {inspectResult.prior_volumes} prior volume{inspectResult.prior_volumes === 1
													? ''
													: 's'} on shelf
											</span>
										{/if}
									{/if}
								</td>
							</tr>
							<tr>
								<td class="label small-caps">Position in series</td>
								<td class="value">
									{#if editing}
										<input
											type="number"
											min="1"
											bind:value={bookOrder}
											disabled={committing || standalone}
										/>
									{:else}
										Volume {toRoman(bookOrder)}
									{/if}
								</td>
							</tr>
							<tr>
								<td class="label small-caps">Chapters detected</td>
								<td class="value">
									{inspectResult.chapters_detected}
									{#if inspectResult.has_prologue}· with prologue{/if}
								</td>
							</tr>
							<tr>
								<td class="label small-caps">Word count</td>
								<td class="value">{inspectResult.word_count.toLocaleString()}</td>
							</tr>
							{#if editing}
								<tr>
									<td class="label small-caps">Standalone</td>
									<td class="value">
										<label class="checkbox-row">
											<input type="checkbox" bind:checked={standalone} disabled={committing} />
											<span class="small-caps">This is a standalone book</span>
										</label>
									</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>

				{#if inspectResult.already_ingested}
					<p class="already-note">This edition is already on the shelf.</p>
				{/if}

				{#if commitError}
					<p class="error" role="alert">{commitError}</p>
				{/if}

				{#if committing}
					<div class="waiting">
						<div class="waiting-bar"><div class="waiting-fill"></div></div>
						<p class="waiting-copy">Reading the file front to back — this takes a moment.</p>
					</div>
				{:else if commitResult}
					<p class="done-note">On the shelf.</p>
					{#if commitResult.excerpt_chapters.length > 0}
						<p class="quarantine-note">
							Back matter from another book was quarantined during ingest and will never be shown.
						</p>
					{/if}
					<div class="actions">
						<button class="btn-ghost small-caps" onclick={reset}>Shelve another</button>
						<a href="/" class="btn-secondary small-caps">Go to library</a>
						<a href="/chat?book={commitResult.book_id}" class="btn-primary">
							<span class="italic">Start reading</span>
						</a>
					</div>
				{:else}
					<div class="actions">
						<button class="btn-primary" onclick={shelve} disabled={!canShelve}>
							<span class="italic">
								{inspectResult.already_ingested ? 'Re-shelve volume' : 'Shelve volume'}
							</span>
						</button>
						<button
							class="btn-ghost small-caps"
							onclick={() => (editing = !editing)}
						>
							{editing ? 'Done editing' : 'Edit fields'}
						</button>
						<p class="reader-note italic">
							Reader position will start at <strong>Chapter 1</strong>.
						</p>
					</div>
				{/if}
			{/if}
		{/if}
	</div>
</div>

<style>
	.upload-layout {
		display: flex;
		gap: var(--sp-16);
	}
	.main-panel {
		flex: 1;
		min-width: 0;
		border-left: var(--hairline);
		padding-left: var(--sp-16);
	}
	.page-title {
		font-family: var(--serif-display);
		font-size: var(--fs-40);
		margin: 0 0 var(--sp-2);
		color: var(--bone);
	}
	.file-line {
		color: var(--bone-muted);
		font-size: var(--fs-13);
		margin-bottom: var(--sp-8);
		text-align: right;
	}
	.entry-body {
		display: flex;
		gap: var(--sp-8);
		align-items: flex-start;
		margin-bottom: var(--sp-6);
	}
	.cover-frame {
		flex-shrink: 0;
		border: var(--hairline);
		border-radius: var(--r-cover);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
	}
	:global(:root[data-theme='light']) .cover-frame {
		box-shadow: 0 4px 14px rgba(31, 36, 32, 0.18);
	}
	.catalog-table {
		flex: 1;
		min-width: 0;
		max-width: 640px;
		border-collapse: collapse;
	}
	.catalog-table td {
		padding: var(--sp-3) 0;
		border-top: var(--hairline);
		vertical-align: middle;
	}
	.catalog-table tr:first-child td {
		border-top: none;
	}
	.catalog-table .label {
		color: var(--brass);
		width: 13.5rem;
		padding-right: var(--sp-6);
	}
	.catalog-table .value {
		font-family: var(--serif-body);
		font-size: var(--fs-18);
		color: var(--bone);
	}
	.series-note {
		display: block;
		font-size: var(--fs-13);
		color: var(--bone-muted);
		margin-top: var(--sp-1);
	}
	.inline-field {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		border: none;
		padding: 0;
		margin: 0;
	}
	.inline-field:disabled {
		opacity: 0.5;
	}
	.new-series-input {
		max-width: 260px;
	}
	select,
	input[type='text'],
	input[type='number'] {
		background: var(--ink-surface);
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-2) var(--sp-3);
		font-family: var(--serif-body);
		font-size: var(--fs-16);
		border-radius: var(--r-chip);
		width: 100%;
		max-width: 320px;
	}
	input[type='number'] {
		max-width: 120px;
	}
	.checkbox-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		cursor: pointer;
		color: var(--bone);
	}
	.already-note {
		color: var(--oxblood);
		font-size: var(--fs-14);
		margin: 0 0 var(--sp-4);
	}
	.done-note {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone);
		margin: 0 0 var(--sp-4);
	}
	.error {
		color: var(--oxblood);
		font-size: var(--fs-14);
	}
	.waiting {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		margin-top: var(--sp-6);
	}
	.waiting-bar {
		height: 2px;
		width: 100%;
		background: var(--ink-hairline);
		overflow: hidden;
		border-radius: 1px;
	}
	.waiting-fill {
		height: 100%;
		width: 40%;
		background: var(--brass);
		animation: sweep 1.6s ease-in-out infinite;
	}
	@keyframes sweep {
		0% {
			transform: translateX(-100%);
		}
		100% {
			transform: translateX(350%);
		}
	}
	.waiting-copy {
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-14);
	}
	.actions {
		display: flex;
		align-items: center;
		gap: var(--sp-6);
		margin-top: var(--sp-6);
		flex-wrap: wrap;
	}
	.reader-note {
		color: var(--bone-muted);
		font-size: var(--fs-14);
		margin-left: auto;
	}
	.quarantine-note {
		font-style: italic;
		font-size: var(--fs-14);
		color: var(--bone-muted);
		margin-bottom: var(--sp-4);
	}
	.btn-primary {
		background: var(--brass);
		border: 1px solid var(--brass);
		color: var(--ink-bg);
		padding: var(--sp-3) var(--sp-6);
		border-radius: var(--r-chip);
		cursor: pointer;
		text-decoration: none;
		display: inline-block;
		font-size: var(--fs-16);
		font-family: var(--serif-display);
	}
	/* --ink-bg is near-white in the light theme, so brass-on-ink-bg loses
	   contrast there -- --bone (near-black in light) reads correctly instead. */
	:global(:root[data-theme='light']) .btn-primary {
		color: var(--bone);
	}
	.btn-primary:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.btn-primary .italic {
		font-style: italic;
	}
	.btn-secondary {
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-3) var(--sp-6);
		border-radius: var(--r-chip);
		text-decoration: none;
		display: inline-block;
	}
	.btn-ghost {
		background: none;
		border: none;
		color: var(--bone-muted);
		text-decoration: underline;
		text-underline-offset: 3px;
		cursor: pointer;
		padding: 0;
	}
</style>
