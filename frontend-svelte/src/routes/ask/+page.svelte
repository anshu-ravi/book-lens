<script lang="ts">
	import { untrack } from 'svelte';
	import libraryStore from '$lib/stores/library.svelte';
	import { queryKnowledgeGraph } from '$lib/api/query';
	import inquiryStore, { loadInquiries, addInquiry, setActiveInquiry } from '$lib/stores/inquiries.svelte';
	import type { ConversationMessage } from '$lib/types';
	import { toRomanLower } from '$lib/utils/roman';

	import InquiriesRail from '$lib/components/ask/InquiriesRail.svelte';
	import QuestionComposer from '$lib/components/ask/QuestionComposer.svelte';
	import InquiryView from '$lib/components/ask/InquiryView.svelte';

	let selectedSeriesId = $state('');
	let loading = $state(false);
	let error = $state('');
	let composing = $state(true);

	// Default to the series currently being read
	$effect(() => {
		if (!selectedSeriesId && libraryStore.data) {
			const reading = libraryStore.data.series.find(s => s.books.some(b => b.status === 'reading'));
			if (reading) selectedSeriesId = reading.id;
		}
	});

	// Load inquiries when series changes
	$effect(() => {
		if (selectedSeriesId) {
			loadInquiries(selectedSeriesId);
			composing = untrack(() => inquiryStore.inquiries.length === 0);
		}
	});

	// Active inquiry
	const activeInquiry = $derived(
		inquiryStore.inquiries.find(i => i.id === inquiryStore.activeId) ?? null
	);
	const activeIndex = $derived(
		inquiryStore.activeId
			? inquiryStore.inquiries.findIndex(i => i.id === inquiryStore.activeId) + 1
			: 1
	);
	const inquiryNumber = $derived(inquiryStore.inquiries.length - activeIndex + 1);

	// Current book info for bookmark anchor
	const currentSeries = $derived(libraryStore.data?.series.find(s => s.id === selectedSeriesId));
	const activeBook = $derived(currentSeries?.books.find(b => b.status === 'reading'));
	const bookmarkChapter = $derived(activeBook ? (activeBook.current_chapter_index ?? 0) + 1 : undefined);

	// Build conversation history from current series inquiries
	function buildHistory(): ConversationMessage[] {
		return inquiryStore.inquiries
			.slice()
			.reverse()
			.flatMap(i => [
				{ role: 'user' as const, content: i.question },
				{ role: 'assistant' as const, content: i.answerMarkdown },
			]);
	}

	async function handleQuestion(question: string) {
		if (!selectedSeriesId) return;
		loading = true;
		error = '';
		composing = false;
		const t0 = performance.now();
		try {
			const res = await queryKnowledgeGraph({
				series_id: selectedSeriesId,
				question,
				conversation_history: buildHistory(),
			});
			const elapsed = performance.now() - t0;
			const volRoman = activeBook
				? toRomanLower(activeBook.position_in_series ?? activeBook.index + 1)
				: 'i';
			const chapNum = bookmarkChapter ?? 0;
			const chapterRange = `Drawn from Ch. 1–${chapNum} of Vol. ${volRoman}`;

			addInquiry({
				id: crypto.randomUUID(),
				question,
				answerMarkdown: res.answer,
				sources: res.sources,
				elapsedMs: elapsed,
				sourceCount: res.sources.length,
				chapterRange,
				volumeRoman: volRoman,
				chapterNum: chapNum,
				ts: Date.now(),
			});
		} catch (e) {
			error = e instanceof Error ? e.message : 'Query failed';
			composing = true;
		} finally {
			loading = false;
		}
	}
</script>

<div class="ask-layout">
	<div class="series-select-bar">
		<span class="series-label small-caps">Series</span>
		<select class="series-select" bind:value={selectedSeriesId}>
			<option value="">— select a series —</option>
			{#each libraryStore.data?.series ?? [] as s (s.id)}
				<option value={s.id}>{s.name}</option>
			{/each}
		</select>
	</div>

	{#if selectedSeriesId}
		<div class="ask-columns">
			<InquiriesRail
				inquiries={inquiryStore.inquiries}
				activeId={inquiryStore.activeId}
				bookTitle={activeBook?.title}
				chapterNum={bookmarkChapter}
				onselect={(id) => { setActiveInquiry(id); composing = false; }}
			/>

			<div class="main-panel">
				{#if loading}
					<div class="loading">
						<span>Consulting the pages…</span>
					</div>
				{:else if error}
					<div class="error-msg">{error}</div>
				{:else if composing || !activeInquiry}
					<QuestionComposer onsubmit={handleQuestion} />
				{:else}
					<InquiryView
						inquiry={activeInquiry}
						{inquiryNumber}
						onFollowUp={() => (composing = true)}
					/>
				{/if}
			</div>
		</div>
	{:else}
		<div class="select-prompt">
			<p>Select a series to begin your inquiry.</p>
		</div>
	{/if}
</div>

<style>
	.ask-layout {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		height: calc(100vh - var(--header-h) - calc(var(--frame-inset) * 2) - calc(var(--sp-8) * 2));
		min-height: 400px;
	}
	.series-select-bar {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
		padding-bottom: var(--sp-4);
		border-bottom: var(--hairline);
		flex-shrink: 0;
	}
	.series-label { color: var(--bone-muted); }
	.series-select {
		font-family: var(--serif-body);
		font-size: var(--fs-16);
		font-style: italic;
		color: var(--bone);
		background: transparent;
		border: none;
		border-bottom: var(--hairline);
		outline: none;
		padding: 2px 0;
		cursor: pointer;
	}
	.series-select option {
		background: var(--ink-surface);
		color: var(--bone);
		font-style: normal;
	}
	.ask-columns {
		display: flex;
		flex: 1;
		min-height: 0;
		border: var(--hairline);
	}
	.main-panel {
		flex: 1;
		overflow-y: auto;
		min-width: 0;
	}
	.loading, .select-prompt {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-18);
	}
	.error-msg {
		padding: var(--sp-8);
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--oxblood);
	}
</style>
