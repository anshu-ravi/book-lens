<script lang="ts">
	import libraryStore from '$lib/stores/library.svelte';
	import { getTimeline } from '$lib/api/library';
	import type { TimelineResponse } from '$lib/types';
	import { toRomanLower } from '$lib/utils/roman';
	import { applyHighlights } from '$lib/utils/highlight';

	import ExploreHeader from '$lib/components/explore/ExploreHeader.svelte';
	import GraphPanel from '$lib/components/explore/GraphPanel.svelte';
	import RecapPanel from '$lib/components/explore/RecapPanel.svelte';
	import Scrubber from '$lib/components/explore/Scrubber.svelte';

	let selectedSeriesId = $state('');
	let toChapter = $state(0);
	let timeline = $state<TimelineResponse | null>(null);
	let loading = $state(false);
	let error = $state('');
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	// Current series bookmark
	const currentSeries = $derived(libraryStore.data?.series.find(s => s.id === selectedSeriesId));
	const readingBook = $derived(currentSeries?.books.find(b => b.status === 'reading'));
	const bookmarkChapter = $derived(readingBook?.current_chapter_index ?? 0);

	// Volume breaks for scrubber
	const volumeBreaks = $derived(() => {
		if (!currentSeries) return [];
		let idx = 0;
		return currentSeries.books.map((book, i) => {
			const breakIdx = idx;
			idx += book.chapters.length;
			return { chapterIndex: breakIdx, label: `Vol. ${toRomanLower(i + 1)}` };
		});
	});

	// Flat chapter list across all books
	const allChapters = $derived(timeline?.chapters ?? []);

	// Recap: concatenate summaries up to toChapter
	const recapText = $derived(() => {
		if (!allChapters.length) return '';
		const relevantChapters = allChapters.filter(ch => ch.chapter_index <= toChapter && ch.summary);
		const rawText = relevantChapters.map(ch => `<p>${ch.summary}</p>`).join('');
		const revealedNames = (timeline?.reveals ?? [])
			.filter(r => r.chapter_index <= toChapter)
			.map(r => r.to_name)
			.filter(Boolean);
		return applyHighlights(rawText, revealedNames);
	});

	const nodeCount = $derived(
		(timeline?.reveals ?? []).filter(r => r.chapter_index <= toChapter).length
	);

	const currentVolumeLabel = $derived(() => {
		if (!currentSeries) return 'vol. i';
		let idx = 0;
		for (let i = 0; i < currentSeries.books.length; i++) {
			const book = currentSeries.books[i];
			if (toChapter < idx + book.chapters.length) {
				return `vol. ${toRomanLower(i + 1)}`;
			}
			idx += book.chapters.length;
		}
		return `vol. ${toRomanLower(currentSeries.books.length)}`;
	});

	const atBookmark = $derived(toChapter >= bookmarkChapter);

	async function loadTimeline() {
		if (!selectedSeriesId) return;
		loading = true;
		error = '';
		try {
			timeline = await getTimeline(selectedSeriesId, toChapter);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load timeline';
		} finally {
			loading = false;
		}
	}

	// Load on series change
	$effect(() => {
		if (selectedSeriesId) {
			toChapter = bookmarkChapter;
			loadTimeline();
		}
	});

	// Debounce scrubber changes
	$effect(() => {
		// Track toChapter changes to debounce timeline refetch
		void toChapter;
		if (!selectedSeriesId || !timeline) return;
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			loadTimeline();
		}, 200);
	});
</script>

<div class="explore-layout">
	<div class="top-bar">
		<span class="series-label small-caps">Series</span>
		<select class="series-select" bind:value={selectedSeriesId}>
			<option value="">— select a series —</option>
			{#each libraryStore.data?.series ?? [] as s (s.id)}
				<option value={s.id}>{s.name}</option>
			{/each}
		</select>
	</div>

	{#if selectedSeriesId}
		<ExploreHeader
			{nodeCount}
			{toChapter}
			volumeLabel={currentVolumeLabel()}
		/>

		{#if error}
			<div class="error">{error}</div>
		{:else}
			<div class="columns">
				<GraphPanel {nodeCount} {toChapter} />

				<RecapPanel
					recap={recapText()}
					{loading}
					{atBookmark}
				/>

				<Scrubber
					chapters={allChapters}
					bind:toChapter
					{bookmarkChapter}
					volumeBreaks={volumeBreaks()}
				/>
			</div>
		{/if}
	{:else}
		<div class="select-prompt">
			<p>Select a series to open the endpaper.</p>
		</div>
	{/if}
</div>

<style>
	.explore-layout {
		display: flex;
		flex-direction: column;
		height: calc(100vh - var(--header-h) - calc(var(--frame-inset) * 2) - calc(var(--sp-8) * 2));
		min-height: 500px;
	}
	.top-bar {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
		padding-bottom: var(--sp-4);
		border-bottom: var(--hairline);
		flex-shrink: 0;
		margin-bottom: var(--sp-4);
	}
	.series-label { color: var(--bone-muted); }
	.series-select {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-16);
		color: var(--bone);
		background: transparent;
		border: none;
		border-bottom: var(--hairline);
		outline: none;
		padding: 2px 0;
	}
	.series-select option {
		background: var(--ink-surface);
		color: var(--bone);
		font-style: normal;
	}
	.columns {
		display: flex;
		flex: 1;
		min-height: 0;
		border: var(--hairline);
	}
	.error {
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--oxblood);
		padding: var(--sp-4);
	}
	.select-prompt {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-18);
	}
	.select-prompt p { margin: 0; }
</style>
