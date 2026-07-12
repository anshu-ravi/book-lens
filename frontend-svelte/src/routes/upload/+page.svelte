<script lang="ts">
	import { goto } from '$app/navigation';
	import { extractMetadata } from '$lib/api/books';
	import { uploadBook } from '$lib/api/library';
	import { refreshLibrary } from '$lib/stores/library.svelte';
	import libraryStore from '$lib/stores/library.svelte';
	import type { ExtractMetadataResponse } from '$lib/types';
	import { sha256Truncated } from '$lib/utils/sha';
	import { humanBytes } from '$lib/utils/file-meta';
	import { extractEpubCover } from '$lib/utils/epub-cover';

	import AcquisitionRail from '$lib/components/upload/AcquisitionRail.svelte';
	import CatalogEntry from '$lib/components/upload/CatalogEntry.svelte';
	import CoverPreview from '$lib/components/upload/CoverPreview.svelte';
	import MetadataTable from '$lib/components/upload/MetadataTable.svelte';
	import DropZone from '$lib/components/upload/DropZone.svelte';
	import ShelveButton from '$lib/components/upload/ShelveButton.svelte';
	import StageStatus from '$lib/components/upload/StageStatus.svelte';

	type Phase = 'idle' | 'extracting' | 'confirming' | 'uploading' | 'done' | 'error';

	let phase: Phase = $state('idle');
	let file: File | null = $state(null);
	let meta: ExtractMetadataResponse | null = $state(null);
	let errorMsg = $state('');
	let shaDisplay = $state('');
	let doneMsg = $state('');
	let coverObjectUrl = $state<string | null>(null);

	// Editable fields
	let title = $state('');
	let author = $state('');
	let seriesName = $state('');
	let seriesPosition = $state('');
	let isSeries = $state(false);

	// Derived file display
	const filename = $derived(file !== null ? (file as File).name : '');
	const fileSize = $derived(file !== null ? humanBytes((file as File).size) : '');

	// Series match note
	const seriesMatchNote = $derived(() => {
		if (!seriesName || !libraryStore.data) return undefined;
		const match = libraryStore.data.series.find(s =>
			s.name.toLowerCase() === seriesName.toLowerCase()
		);
		if (match) return `matched · ${match.books.length} prior volume${match.books.length !== 1 ? 's' : ''} on shelf`;
		return undefined;
	});

	async function onFile(f: File) {
		// Revoke any previous object URL
		if (coverObjectUrl) { URL.revokeObjectURL(coverObjectUrl); coverObjectUrl = null; }

		file = f;
		shaDisplay = '';
		errorMsg = '';
		meta = null;
		phase = 'extracting';
		try {
			const [shaResult, metaResult, coverResult] = await Promise.allSettled([
				sha256Truncated(f),
				extractMetadata(f),
				extractEpubCover(f),
			]);

			if (metaResult.status === 'rejected') throw metaResult.reason;

			shaDisplay = shaResult.status === 'fulfilled' ? shaResult.value : '';
			meta = metaResult.value;
			coverObjectUrl = coverResult.status === 'fulfilled' ? coverResult.value : null;

			title = meta.book_name ?? meta.title;
			author = meta.author ?? '';
			seriesName = meta.series_name ?? '';
			seriesPosition = meta.series_position?.toString() ?? '';
			isSeries = meta.is_series;
			phase = 'confirming';
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : 'Extraction failed';
			phase = 'error';
		}
	}

	async function confirmUpload() {
		if (!file) return;
		phase = 'uploading';
		errorMsg = '';
		try {
			const form = new FormData();
			form.append('file', file);
			form.append('title', title);
			form.append('is_series', isSeries ? 'true' : 'false');
			if (author) form.append('author', author);
			if (seriesName) form.append('series_name', seriesName);
			if (seriesPosition) form.append('series_position', seriesPosition);

			await uploadBook(form);

			const volumeWord = seriesName
				? `${seriesName} now holds ${(libraryStore.data?.series.find(s => s.name === seriesName)?.books.length ?? 0) + 1} volumes.`
				: 'Volume added to your library.';
			doneMsg = `Added. ${volumeWord}`;
			phase = 'done';

			// Refresh store so Library page is current on arrival
			await refreshLibrary();
			setTimeout(() => goto('/library'), 2000);
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : 'Upload failed';
			phase = 'error';
		}
	}

	function reset() {
		if (coverObjectUrl) { URL.revokeObjectURL(coverObjectUrl); coverObjectUrl = null; }
		phase = 'idle';
		file = null;
		meta = null;
		errorMsg = '';
		shaDisplay = '';
	}
</script>

<div class="upload-layout">
	<AcquisitionRail {phase} />

	<main class="main-panel">
		{#if phase === 'idle'}
			<DropZone onfile={onFile} />

		{:else if phase === 'extracting'}
			<div class="reading-note">
				<CoverPreview title="…" shimmer />
				<p class="extract-note">Reading the title page…</p>
			</div>

		{:else if phase === 'confirming' || phase === 'uploading'}
			<CatalogEntry {filename} {fileSize} sha={shaDisplay} />

			<div class="body-columns">
				<CoverPreview
					title={title}
					author={author}
					seriesId={seriesName || 'default'}
					coverUrl={coverObjectUrl ?? undefined}
				/>
				<div class="meta-right">
					<MetadataTable
						bind:title
						bind:author
						bind:seriesName
						bind:seriesPosition
						bind:isSeries
						seriesMatchNote={seriesMatchNote()}
					/>
					<div class="cta-row">
						<ShelveButton
							disabled={phase === 'uploading'}
							loading={phase === 'uploading'}
							onclick={confirmUpload}
						/>
						<StageStatus {phase} />
						<span class="reader-note">Reader position will start at Chapter 1.</span>
					</div>
				</div>
			</div>

		{:else if phase === 'done'}
			<div class="done-panel">
				<p class="done-msg">{doneMsg}</p>
				<p class="done-redirect">Returning to your library…</p>
			</div>

		{:else if phase === 'error'}
			<div class="error-panel">
				<p class="error-msg">The shelving did not take. {errorMsg}</p>
				<button class="try-again small-caps" onclick={reset}>Try again</button>
			</div>
		{/if}
	</main>
</div>

<style>
	.upload-layout {
		display: flex;
		gap: var(--sp-8);
		align-items: flex-start;
		min-height: 500px;
	}
	.main-panel {
		flex: 1;
		min-width: 0;
	}
	.body-columns {
		display: flex;
		gap: var(--sp-8);
		align-items: flex-start;
	}
	.meta-right { flex: 1; }
	.cta-row {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
		margin-top: var(--sp-6);
		flex-wrap: wrap;
	}
	.reader-note {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--bone-faint);
		margin-left: auto;
	}
	.extract-note {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone-muted);
		margin-top: var(--sp-4);
	}
	.reading-note { display: flex; flex-direction: column; align-items: flex-start; }
	.done-panel, .error-panel { padding: var(--sp-8) 0; }
	.done-msg {
		font-family: var(--serif-body);
		font-size: var(--fs-22);
		color: var(--bone);
		margin: 0 0 var(--sp-2);
	}
	.done-redirect {
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-16);
		margin: 0;
	}
	.error-msg {
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--oxblood);
		font-size: var(--fs-18);
		margin: 0 0 var(--sp-4);
	}
	.try-again {
		background: none;
		border: 1px solid var(--oxblood);
		color: var(--oxblood);
		padding: var(--sp-2) var(--sp-6);
		cursor: pointer;
		border-radius: var(--r-chip);
	}
</style>
