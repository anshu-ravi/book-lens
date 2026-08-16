<script lang="ts">
	import { onMount } from 'svelte';
	import { getSeries, uploadBook, ApiError } from '$lib/api';
	import type { SeriesSummary, UploadResponse } from '$lib/types';
	import { slugify } from '$lib/utils/series-name';
	import DropZone from '$lib/components/upload/DropZone.svelte';
	import StepRail from '$lib/components/upload/StepRail.svelte';

	const NEW_SERIES = '__new__';

	let file = $state<File | null>(null);
	let allSeries = $state<SeriesSummary[]>([]);
	let selectedSeries = $state<string>('');
	let newSeriesName = $state('');
	let bookOrder = $state<number>(1);
	let standalone = $state(false);
	let submitting = $state(false);
	let error = $state('');
	let result = $state<UploadResponse | null>(null);

	const step = $derived<1 | 2 | 3>(result ? 3 : file ? 2 : 1);
	const isNewSeries = $derived(selectedSeries === NEW_SERIES);
	const standaloneSeries = $derived(file ? slugify(file.name.replace(/\.epub$/i, '')) : '');
	const effectiveSeries = $derived(
		standalone ? standaloneSeries : isNewSeries ? newSeriesName.trim() : selectedSeries,
	);

	onMount(async () => {
		try {
			const res = await getSeries();
			allSeries = res.series;
		} catch {
			// non-fatal: the "new series" option still works without the list
		}
	});

	function onFile(f: File) {
		file = f;
		error = '';
	}

	function fileSize(f: File): string {
		const mb = f.size / (1024 * 1024);
		return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(f.size / 1024)} KB`;
	}

	function onSeriesChange() {
		if (isNewSeries) {
			bookOrder = 1;
		} else {
			const s = allSeries.find((s) => s.id === selectedSeries);
			bookOrder = s?.next_order ?? 1;
		}
	}

	async function shelve() {
		if (!file || !effectiveSeries) return;
		error = '';
		submitting = true;
		try {
			result = await uploadBook(file, effectiveSeries, standalone ? 1 : bookOrder, standalone);
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not shelve the volume.';
		} finally {
			submitting = false;
		}
	}

	function reset() {
		file = null;
		result = null;
		selectedSeries = '';
		newSeriesName = '';
		bookOrder = 1;
		standalone = false;
		error = '';
	}
</script>

<svelte:head>
	<title>BookLens · Upload</title>
</svelte:head>

<div class="upload-layout">
	<StepRail {step} />

	<div class="main-panel">
		{#if step === 1}
			<h1 class="page-title">Upload</h1>
			<DropZone onfile={onFile} />
		{:else if step === 2}
			<h1 class="page-title">Catalog entry</h1>
			<p class="file-line mono">{file?.name} · {file ? fileSize(file) : ''}</p>

			<form class="catalog-form" onsubmit={(e) => { e.preventDefault(); shelve(); }}>
				<label class="checkbox-row">
					<input type="checkbox" bind:checked={standalone} />
					<span class="small-caps">This is a standalone book</span>
				</label>

				{#if !standalone}
				<div class="field">
					<label class="small-caps" for="series-select">Series</label>
					<select id="series-select" bind:value={selectedSeries} onchange={onSeriesChange} required>
						<option value="" disabled>Choose a series…</option>
						{#each allSeries as s (s.id)}
							<option value={s.id}>{s.id}</option>
						{/each}
						<option value={NEW_SERIES}>＋ new series…</option>
					</select>
				</div>

				{#if isNewSeries}
					<div class="field">
						<label class="small-caps" for="new-series">New series name</label>
						<input id="new-series" type="text" bind:value={newSeriesName} required />
					</div>
				{/if}

				<div class="field">
					<label class="small-caps" for="order">Position in series</label>
					<input id="order" type="number" min="1" bind:value={bookOrder} required />
				</div>

				<p class="explainer">
					Books in the same series share a reading timeline — a volume filed under the wrong
					series will not see its predecessors.
				</p>
				{:else}
					<p class="explainer">A standalone sits on its own shelf, outside any series carousel.</p>
				{/if}

				{#if error}
					<p class="error" role="alert">{error}</p>
				{/if}

				{#if submitting}
					<div class="waiting">
						<div class="waiting-bar"><div class="waiting-fill"></div></div>
						<p class="waiting-copy">Reading the file front to back — this takes a moment.</p>
					</div>
				{:else}
					<div class="form-actions">
						<button type="button" class="btn-ghost small-caps" onclick={reset}>Start over</button>
						<button type="submit" class="btn-primary" disabled={!effectiveSeries}>
							<span class="italic">Shelve volume</span>
						</button>
					</div>
				{/if}
			</form>
		{:else if step === 3 && result}
			<h1 class="page-title">On the shelf</h1>
			<table class="result-table">
				<tbody>
					<tr><td class="small-caps">Title</td><td>{result.title}</td></tr>
					<tr><td class="small-caps">Author</td><td>{result.author}</td></tr>
					<tr><td class="small-caps">Series</td><td>{effectiveSeries}</td></tr>
					<tr><td class="small-caps">Position</td><td>{result.book_order}</td></tr>
					<tr><td class="small-caps">Chapters</td><td>{result.chapters}</td></tr>
					<tr><td class="small-caps">Paragraphs</td><td>{result.paragraphs}</td></tr>
				</tbody>
			</table>

			{#if result.excerpt_chapters.length > 0}
				<p class="quarantine-note">
					Back matter from another book was quarantined during ingest and will never be shown.
				</p>
			{/if}

			<div class="form-actions">
				<button class="btn-ghost small-caps" onclick={reset}>Shelve another</button>
				<a href="/" class="btn-primary italic">Go to library</a>
			</div>
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
		max-width: 640px;
	}
	.page-title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-40);
		margin: 0 0 var(--sp-6);
		color: var(--bone);
	}
	.file-line {
		color: var(--bone-muted);
		font-size: var(--fs-13);
		margin-bottom: var(--sp-6);
	}
	.catalog-form {
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.field label {
		color: var(--bone-muted);
	}
	.checkbox-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		cursor: pointer;
		color: var(--bone);
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
	}
	.explainer {
		font-style: italic;
		font-size: var(--fs-14);
		color: var(--bone-muted);
	}
	.error {
		color: var(--oxblood);
		font-size: var(--fs-14);
	}
	.waiting {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
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
	.form-actions {
		display: flex;
		align-items: center;
		gap: var(--sp-6);
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
	.btn-primary .italic,
	.btn-primary.italic {
		font-style: italic;
		font-family: var(--serif-display);
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
	.result-table {
		width: 100%;
		border-collapse: collapse;
		margin-bottom: var(--sp-6);
	}
	.result-table td {
		padding: var(--sp-3) 0;
		border-top: 1px solid var(--ink-hairline);
	}
	.result-table td:first-child {
		color: var(--bone-muted);
		width: 40%;
	}
	.quarantine-note {
		font-style: italic;
		font-size: var(--fs-14);
		color: var(--bone-muted);
		margin-bottom: var(--sp-6);
	}
</style>
