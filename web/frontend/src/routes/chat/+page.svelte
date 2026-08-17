<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import {
		getLibrary,
		createChatSession,
		sendMessage,
		undoTurn,
		ApiError,
	} from '$lib/api';
	import type { Book, MessageDebug } from '$lib/types';
	import { renderAnswer } from '$lib/utils/render-answer';
	import CitationPopover from '$lib/components/chat/CitationPopover.svelte';

	interface Turn {
		question: string;
		answer?: string;
		citations?: string[];
		debug?: MessageDebug;
	}

	let books = $state<Book[]>([]);
	let selectedBookId = $state<string>('');
	let sessionId = $state<string | null>(null);
	let bookTitle = $state('');
	let priorTitles = $state<string[]>([]);
	let chapterLabel = $state('');
	let tokenEstimate = $state(0);
	let sessionCost = $state(0);
	let noPositionError = $state(false);
	let sessionError = $state('');

	let turns = $state<Turn[]>([]);
	let question = $state('');
	let sending = $state(false);
	let debugOn = $state(false);
	let citation = $state<{ id: string; rect: DOMRect } | null>(null);
	let controller: AbortController | null = null;

	let threadEl = $state<HTMLDivElement | null>(null);
	let textareaEl = $state<HTMLTextAreaElement | null>(null);

	// Chips are raw HTML from renderAnswer, so the "active" chip is tracked by
	// syncing a class onto the DOM rather than through template bindings.
	$effect(() => {
		const activeId = citation?.id ?? null;
		const chips = threadEl?.querySelectorAll<HTMLElement>('.citation-chip') ?? [];
		for (const chip of chips) {
			chip.classList.toggle('active', chip.dataset.citationId === activeId);
		}
	});

	onMount(async () => {
		try {
			const res = await getLibrary();
			books = res.series.flatMap((s) => s.books.filter((b) => b.status !== 'unread'));
			const wanted = $page.url.searchParams.get('book');
			if (wanted && books.some((b) => b.id === wanted)) {
				selectedBookId = wanted;
			} else if (books.length > 0) {
				selectedBookId = books[0].id;
			}
			if (selectedBookId) await startSession(selectedBookId);
		} catch (e) {
			sessionError = e instanceof ApiError ? e.detail : 'Could not load your library.';
		}
	});

	async function startSession(bookId: string) {
		sessionError = '';
		noPositionError = false;
		sessionId = null;
		turns = [];
		sessionCost = 0;
		citation = null;
		try {
			const res = await createChatSession(bookId);
			sessionId = res.session_id;
			bookTitle = res.book_title;
			priorTitles = res.prior_titles;
			chapterLabel = res.chapter_label;
			tokenEstimate = res.token_estimate;
		} catch (e) {
			if (e instanceof ApiError && e.status === 409) {
				noPositionError = true;
			} else {
				sessionError = e instanceof ApiError ? e.detail : 'Could not start a chat session.';
			}
		}
	}

	async function onBookChange() {
		if (selectedBookId) await startSession(selectedBookId);
	}

	function scopeLine(): string {
		// Prior volumes are always whole -- nobody reads book 3 without books 1 and 2.
		const head = priorTitles.length ? `${priorTitles.join(', ')} (whole) + ${bookTitle}` : bookTitle;
		const where = /^chapter/i.test(chapterLabel) ? chapterLabel : `chapter ${chapterLabel}`;
		const tokens =
			tokenEstimate >= 1000 ? `~${Math.round(tokenEstimate / 1000)}k` : String(tokenEstimate);
		return `${head} through ${where} · ${tokens} tokens in context`;
	}

	async function scrollToBottom() {
		await tick();
		threadEl?.scrollTo({ top: threadEl.scrollHeight });
	}

	async function scrollLastQuestionIntoView() {
		// Answers run long; landing on the question reads better than landing mid-prose.
		await tick();
		const blocks = threadEl?.querySelectorAll('.question-block');
		blocks?.[blocks.length - 1]?.scrollIntoView({ block: 'start' });
	}

	function autoGrow() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
		textareaEl.style.height = `${Math.min(textareaEl.scrollHeight, 200)}px`;
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit();
		}
	}

	async function submit() {
		const q = question.trim();
		if (!q || !sessionId || sending) return;

		question = '';
		autoGrow();
		turns.push({ question: q });
		await scrollToBottom();

		sending = true;
		controller = new AbortController();
		try {
			const res = await sendMessage(sessionId, q, controller.signal);
			const t = turns[turns.length - 1];
			t.answer = res.answer;
			t.citations = res.citations;
			t.debug = res.debug;
			sessionCost = res.debug.session_cost_usd;
			await scrollLastQuestionIntoView();
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') {
				// cancelled below in cancel()
			} else {
				turns.pop();
				sessionError = e instanceof ApiError ? e.detail : 'That question could not be answered.';
			}
		} finally {
			sending = false;
			controller = null;
		}
	}

	async function cancel() {
		controller?.abort();
		turns.pop();
		if (sessionId) {
			try {
				await undoTurn(sessionId);
			} catch {
				// best-effort: the server-side turn may already be gone
			}
		}
	}

	function onThreadClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		const chip = target.closest('.citation-chip') as HTMLElement | null;
		if (chip) {
			const id = chip.dataset.citationId;
			if (!id) return;
			if (citation?.id === id) {
				citation = null;
			} else {
				citation = { id, rect: chip.getBoundingClientRect() };
			}
		}
	}

	function onThreadScroll() {
		citation = null;
	}

	function onWindowClick(e: MouseEvent) {
		if (!citation) return;
		const target = e.target as HTMLElement;
		if (target.closest('.citation-chip') || target.closest('.citation-popover')) return;
		citation = null;
	}

	function onWindowKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') citation = null;
	}
</script>

<svelte:head>
	<title>BookLens · Chat</title>
</svelte:head>

<svelte:window onclick={onWindowClick} onkeydown={onWindowKeydown} />

<div class="chat-page">
	<div class="chat-head">
		<div class="head-row">
			<select bind:value={selectedBookId} onchange={onBookChange} aria-label="Book">
				{#each books as b (b.id)}
					<option value={b.id}>{b.title}</option>
				{/each}
			</select>
			<label class="debug-toggle small-caps">
				<input type="checkbox" bind:checked={debugOn} />
				Debug
			</label>
			{#if sessionCost > 0}
				<span class="cost small-caps">session · ${sessionCost.toFixed(4)}</span>
			{/if}
		</div>

		{#if sessionError}
			<p class="error">{sessionError}</p>
		{:else if noPositionError}
			<p class="error">
				You haven't set a reading position for this book yet. <a href="/">Go to the library →</a>
			</p>
		{:else if sessionId}
			<p class="scope-line small-caps">{scopeLine()}</p>
			<p class="scope-promise">Answers will not reach beyond this point.</p>
		{/if}
	</div>

	{#if sessionId}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="thread"
			bind:this={threadEl}
			onclick={onThreadClick}
			onscroll={onThreadScroll}
			aria-live="polite"
		>
			{#each turns as t, i (i)}
				<div class="question-block">
					<p class="question">{t.question}</p>
				</div>
				{#if t.answer !== undefined}
					<div class="answer-block">
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html renderAnswer(t.answer, t.citations ?? [])}
						{#if debugOn && t.debug}
							<p class="debug-line mono">
								ctx {t.debug.context_tokens} · prompt {t.debug.prompt_tokens ?? '?'} · cached {t.debug.cached_tokens ?? 0} · turn ${(t.debug.turn_cost_usd ?? 0).toFixed(4)} · session ${t.debug.session_cost_usd.toFixed(4)}
							</p>
						{/if}
					</div>
				{:else if i === turns.length - 1 && sending}
					<div class="answer-block">
						<p class="pending">Reading…</p>
					</div>
				{/if}
			{/each}
		</div>

		<div class="composer">
			<textarea
				bind:this={textareaEl}
				bind:value={question}
				oninput={autoGrow}
				onkeydown={onKeydown}
				placeholder="Ask about what you've read so far…"
				rows="1"
				disabled={sending}
			></textarea>
			{#if sending}
				<button class="send-btn cancel small-caps" onclick={cancel}>Cancel</button>
			{:else}
				<button class="send-btn small-caps" onclick={submit} disabled={!question.trim()}>Send</button>
			{/if}
		</div>

		{#if citation && sessionId}
			<CitationPopover
				sessionId={sessionId}
				citationId={citation.id}
				anchor={citation.rect}
				onclose={() => (citation = null)}
			/>
		{/if}
	{/if}
</div>

<style>
	.chat-page {
		display: flex;
		flex-direction: column;
		width: 100%;
		max-width: 820px;
		margin: 0 auto;
		height: calc(100vh - var(--header-h) - calc(var(--frame-inset) * 2) - calc(var(--sp-8) * 2));
	}
	.chat-head {
		flex-shrink: 0;
		border-bottom: var(--hairline);
		padding-bottom: var(--sp-4);
		margin-bottom: var(--sp-4);
	}
	.head-row {
		display: flex;
		align-items: center;
		gap: var(--sp-6);
		margin-bottom: var(--sp-3);
	}
	select {
		background: var(--ink-surface);
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-2) var(--sp-3);
		font-family: var(--serif-body);
		font-size: var(--fs-16);
		border-radius: var(--r-chip);
	}
	.debug-toggle {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		color: var(--bone-muted);
		cursor: pointer;
	}
	.cost {
		margin-left: auto;
		color: var(--bone-faint);
	}
	.error {
		color: var(--oxblood);
	}
	.error a {
		color: var(--brass);
	}
	.scope-line {
		color: var(--brass);
		font-style: italic;
		font-family: var(--serif-body);
		text-transform: none;
		letter-spacing: normal;
		font-size: var(--fs-14);
	}
	.scope-promise {
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-13);
		margin: var(--sp-1) 0 0;
	}
	.thread {
		flex: 1;
		overflow-y: auto;
		padding-right: var(--sp-2);
		padding-bottom: var(--sp-6);
	}
	.question-block {
		display: flex;
		justify-content: flex-end;
		margin: var(--sp-6) 0 var(--sp-3);
	}
	.question {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone);
		text-align: right;
		max-width: 100%;
		margin: 0;
	}
	.answer-block {
		max-width: 100%;
		color: var(--bone);
		line-height: 1.7;
		margin-bottom: var(--sp-6);
	}
	.answer-block :global(p) {
		margin: 0 0 var(--sp-4);
	}
	.answer-block :global(.citation-chip) {
		display: inline-block;
		vertical-align: super;
		font-size: 10px;
		line-height: 1;
		background: color-mix(in srgb, var(--brass) 18%, transparent);
		color: var(--brass);
		border: none;
		border-radius: var(--r-chip);
		padding: 1px 4px;
		margin: 0 2px;
		cursor: pointer;
	}
	.answer-block :global(.citation-chip.active) {
		background: var(--brass);
		color: var(--ink-bg);
	}
	.pending {
		font-style: italic;
		color: var(--bone-muted);
	}
	.debug-line {
		color: var(--bone-faint);
		font-size: var(--fs-12);
		margin-top: var(--sp-2);
	}
	.composer {
		flex-shrink: 0;
		display: flex;
		gap: var(--sp-4);
		align-items: flex-end;
		border-top: var(--hairline);
		padding-top: var(--sp-4);
	}
	textarea {
		flex: 1;
		background: var(--ink-surface);
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-3);
		font-family: var(--serif-body);
		font-size: var(--fs-16);
		border-radius: var(--r-chip);
		resize: none;
		max-height: 200px;
	}
	.send-btn {
		background: var(--brass);
		border: 1px solid var(--brass);
		color: var(--ink-bg);
		padding: var(--sp-3) var(--sp-6);
		border-radius: var(--r-chip);
		cursor: pointer;
		flex-shrink: 0;
	}
	/* --ink-bg is near-white in the light theme, so brass-on-ink-bg loses
	   contrast there -- --bone (near-black in light) reads correctly instead. */
	:global(:root[data-theme='light']) .send-btn {
		color: var(--bone);
	}
	.send-btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.send-btn.cancel {
		background: var(--oxblood);
		border-color: var(--oxblood);
		color: var(--bone);
	}
</style>
