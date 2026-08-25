<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import {
		ApiError,
		askInConversation,
		createChatSession,
		deleteConversation,
		getCitationMarks,
		getCitationWindow,
		getLibrary,
		listConversations,
		newConversation,
		openConversation,
		undoConversationTurn,
	} from '$lib/api';
	import type {
		Book,
		CitationMark,
		ConversationGroup,
		ConversationResponse,
		MessageDebug,
		SessionHeader,
	} from '$lib/types';
	import { renderAnswer } from '$lib/utils/render-answer';
	import BoundBar from '$lib/components/chat/BoundBar.svelte';
	import CitationSheet from '$lib/components/chat/CitationSheet.svelte';
	import ConversationList from '$lib/components/chat/ConversationList.svelte';

	interface Turn {
		question: string;
		answer?: string;
		citations: string[];
		chapterLabel?: string;
		debug?: MessageDebug;
	}

	let books = $state<Book[]>([]);
	let groups = $state<ConversationGroup[]>([]);
	// Collapsed by default: the thread is what the reader came for.
	let listOpen = $state(false);

	let header = $state<SessionHeader | null>(null);
	// Null while the chat is a draft: a conversation is only written once it
	// has a question in it, so opening the screen leaves nothing behind.
	let conversationId = $state<string | null>(null);
	let draftBookId = $state<string | null>(null);
	let turns = $state<Turn[]>([]);
	let startedAtLabel = $state('');
	let movedOn = $state(false);

	let question = $state('');
	let sending = $state(false);
	let debugOn = $state(false);
	let sessionCost = $state(0);
	let loadError = $state('');
	let noPosition = $state<string | null>(null);

	let marks = $state<CitationMark[]>([]);
	let openCitation = $state<string | null>(null);
	let hoveredTurn = $state<number | null>(null);

	let peek = $state<{ id: string; text: string; x: number; y: number } | null>(null);
	const peekCache = new Map<string, string>();
	let peekTimer: ReturnType<typeof setTimeout> | null = null;

	let selection = $state<{ text: string; x: number; y: number } | null>(null);

	let switching = $state(false);

	let threadEl = $state<HTMLDivElement | null>(null);
	let textareaEl = $state<HTMLTextAreaElement | null>(null);
	let controller: AbortController | null = null;

	// Which marks belong to the answer under the cursor, so hovering an answer
	// lights exactly the passages it leaned on.
	const litIds = $derived(
		new Set(hoveredTurn === null ? [] : (turns[hoveredTurn]?.citations ?? [])),
	);

	// Chips are raw HTML from renderAnswer, so the active one is tracked by
	// syncing a class onto the DOM rather than through template bindings.
	$effect(() => {
		const activeId = openCitation;
		const chips = threadEl?.querySelectorAll<HTMLElement>('.citation-chip') ?? [];
		for (const chip of chips) {
			chip.classList.toggle('active', chip.dataset.citationId === activeId);
		}
	});

	onMount(async () => {
		try {
			const lib = await getLibrary();
			books = lib.series.flatMap((s) => s.books.filter((b) => b.status !== 'unread'));
		} catch (e) {
			loadError = e instanceof ApiError ? e.detail : 'Could not load your library.';
			return;
		}
		await refreshList();

		const wantedConversation = $page.url.searchParams.get('conversation');
		const wantedBook = $page.url.searchParams.get('book');
		if (wantedConversation) {
			await load(wantedConversation);
		} else if (wantedBook && books.some((b) => b.id === wantedBook)) {
			await start(wantedBook);
		} else {
			const lastBook = groups[0]?.book_id;
			const book = books.find((b) => b.id === lastBook) ?? books[0];
			if (book) await start(book.id);
		}
	});

	async function refreshList() {
		try {
			groups = (await listConversations()).groups;
		} catch {
			// The index is a convenience; a failed fetch just leaves it empty.
		}
	}

	function adopt(res: ConversationResponse) {
		header = res;
		conversationId = res.conversation.id;
		draftBookId = null;
		turns = res.turns.map((t) => ({
			question: t.question,
			answer: t.answer,
			citations: t.citations,
			chapterLabel: t.chapter_label,
		}));
		startedAtLabel = res.started_at_chapter_label;
		movedOn = res.moved_on;
		sessionCost = 0;
		openCitation = null;
		hoveredTurn = null;
		loadError = '';
		noPosition = null;
		void refreshMarks();
	}

	/** Open a draft on a book: a live session with no conversation row behind it. */
	async function start(bookId: string) {
		try {
			const session = await createChatSession(bookId);
			header = session;
			conversationId = null;
			draftBookId = bookId;
			turns = [];
			marks = [];
			startedAtLabel = '';
			movedOn = false;
			sessionCost = 0;
			openCitation = null;
			hoveredTurn = null;
			loadError = '';
			noPosition = null;
			switching = false;
			await tick();
			textareaEl?.focus();
		} catch (e) {
			handleOpenError(e, bookId);
		}
	}

	async function load(id: string) {
		try {
			adopt(await openConversation(id));
			await scrollToBottom();
			textareaEl?.focus();
		} catch (e) {
			handleOpenError(e, null);
		}
	}

	function handleOpenError(e: unknown, bookId: string | null) {
		if (e instanceof ApiError && e.status === 409) {
			noPosition = bookId;
			header = null;
			conversationId = null;
		} else {
			loadError = e instanceof ApiError ? e.detail : 'Could not open that conversation.';
		}
	}

	async function remove(id: string) {
		try {
			await deleteConversation(id);
		} catch {
			// Already gone is the outcome we wanted anyway.
		}
		await refreshList();
		if (id === conversationId) {
			const bookId = header?.book_id;
			if (bookId) await start(bookId);
			else {
				header = null;
				conversationId = null;
				turns = [];
			}
		}
	}

	async function refreshMarks() {
		const sid = header?.session_id;
		const ids = [...new Set(turns.flatMap((t) => t.citations))];
		if (!sid || ids.length === 0) {
			marks = [];
			return;
		}
		try {
			marks = (await getCitationMarks(sid, ids)).marks;
		} catch {
			marks = [];
		}
	}

	async function submit() {
		const q = question.trim();
		if (!q || sending || (!conversationId && !draftBookId)) return;

		question = '';
		autoGrow();
		selection = null;
		turns.push({ question: q, citations: [] });
		await scrollToBottom();

		sending = true;
		controller = new AbortController();
		let named = false;
		try {
			// The first question is what brings the conversation into existence.
			if (!conversationId && draftBookId) {
				const created = await newConversation(draftBookId, header?.session_id);
				conversationId = created.conversation.id;
				draftBookId = null;
				named = true;
				if (header) header.session_id = created.session_id;
			}
			const res = await askInConversation(conversationId!, q, controller.signal);
			const t = turns[turns.length - 1];
			t.answer = res.answer;
			t.citations = res.citations;
			t.chapterLabel = res.chapter_label;
			t.debug = res.debug;
			sessionCost = res.debug.session_cost_usd;
			if (header) header.session_id = res.session_id;
			await refreshMarks();
			await refreshList();
			await scrollToLastQuestion();
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') {
				// handled in cancel()
			} else {
				turns.pop();
				loadError = e instanceof ApiError ? e.detail : 'That question could not be answered.';
			}
			// A conversation named a moment ago for a question that never landed
			// would otherwise sit in the list empty.
			if (named && conversationId && turns.length === 0) {
				const orphan = conversationId;
				conversationId = null;
				draftBookId = header?.book_id ?? null;
				await deleteConversation(orphan).catch(() => {});
				await refreshList();
			}
		} finally {
			sending = false;
			controller = null;
		}
	}

	async function cancel() {
		controller?.abort();
		turns.pop();
		if (!conversationId) return;
		try {
			await undoConversationTurn(conversationId);
		} catch {
			// Best effort: the server-side turn may never have landed.
		}
		if (turns.length === 0) {
			const orphan = conversationId;
			conversationId = null;
			draftBookId = header?.book_id ?? null;
			await deleteConversation(orphan).catch(() => {});
		}
		await refreshList();
	}

	async function scrollToBottom() {
		await tick();
		if (turns.length === 0) return;
		threadEl?.scrollTo({ top: threadEl.scrollHeight });
	}

	async function scrollToLastQuestion() {
		// Answers run long; landing on the question reads better than landing mid-prose.
		await tick();
		const blocks = threadEl?.querySelectorAll('.turn');
		blocks?.[blocks.length - 1]?.scrollIntoView({ block: 'start', behavior: 'smooth' });
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

	function onThreadClick(e: MouseEvent) {
		const chip = (e.target as HTMLElement).closest('.citation-chip') as HTMLElement | null;
		if (!chip) return;
		const id = chip.dataset.citationId;
		if (!id) return;
		openCitation = openCitation === id ? null : id;
		if (peekTimer) clearTimeout(peekTimer);
		peek = null;
	}

	function onThreadOver(e: MouseEvent) {
		const chip = (e.target as HTMLElement).closest('.citation-chip') as HTMLElement | null;
		if (peekTimer) clearTimeout(peekTimer);
		if (!chip) {
			peek = null;
			return;
		}
		const id = chip.dataset.citationId;
		const sid = header?.session_id;
		if (!id || !sid || id === openCitation) return;
		const rect = chip.getBoundingClientRect();
		peekTimer = setTimeout(async () => {
			let text = peekCache.get(id);
			if (text === undefined) {
				try {
					const res = await getCitationWindow(sid, id, 0);
					text = res.paragraphs.find((p) => p.citation_id === id)?.text ?? '';
					peekCache.set(id, text);
				} catch {
					return;
				}
			}
			if (!text) return;
			peek = { id, text, x: rect.left, y: rect.top };
		}, 220);
	}

	function onThreadScroll() {
		peek = null;
		selection = null;
	}

	/** A phrase the reader has selected inside an answer becomes the next question. */
	function onThreadMouseUp() {
		const sel = window.getSelection();
		const text = sel?.toString().trim() ?? '';
		if (!sel || text.length < 3 || sel.isCollapsed) {
			selection = null;
			return;
		}
		const anchor = sel.anchorNode?.parentElement;
		if (!anchor?.closest('.answer')) {
			selection = null;
			return;
		}
		const rect = sel.getRangeAt(0).getBoundingClientRect();
		selection = { text, x: rect.left + rect.width / 2, y: rect.top };
	}

	function askAboutSelection() {
		if (!selection) return;
		const phrase = selection.text.length > 160 ? `${selection.text.slice(0, 159)}…` : selection.text;
		question = `About "${phrase}" — `;
		selection = null;
		window.getSelection()?.removeAllRanges();
		textareaEl?.focus();
		tick().then(autoGrow);
	}

	function onWindowKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			openCitation = null;
			peek = null;
			selection = null;
		}
	}
</script>

<svelte:head>
	<title>BookLens · Chat</title>
</svelte:head>

<svelte:window onkeydown={onWindowKeydown} />

<div class="chat">
	<div class="pane">
		<div class="convo">
		{#if loadError}
			<p class="error">{loadError}</p>
		{/if}

		{#if noPosition !== null}
			<div class="middle">
				<p class="none">
					You haven't set a reading position for this book yet.
					<a href="/">Go to the library →</a>
				</p>
			</div>
		{:else if header}
			<div class="head">
				<div class="wash" aria-hidden="true">
					{#if books.find((b) => b.id === header?.book_id)?.has_cover}
						<img src={`/api/books/${header.book_id}/cover`} alt="" />
					{/if}
					<span class="fade"></span>
				</div>
				<div class="head-row">
					<div class="ident">
						<div class="cover">
							{#if books.find((b) => b.id === header?.book_id)?.has_cover}
								<img src={`/api/books/${header.book_id}/cover`} alt="" />
							{:else}
								<span class="fb"></span>
							{/if}
						</div>
						<div class="titles">
							{#if header.prior_books.length > 0}
								<span class="small-caps series">
									{header.series_id.replace(/-/g, ' ')} · book {header.prior_books.length + 1}
								</span>
							{/if}
							<h1>{header.book_title}</h1>
							{#if header.book_author}
								<span class="author">{header.book_author}</span>
							{/if}
						</div>
					</div>

					<div class="switcher">
						<button
							type="button"
							class="small-caps switch"
							onclick={() => (switching = !switching)}
						>
							Switch book
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
								<path d="M6 9l6 6 6-6" />
							</svg>
						</button>
						{#if switching}
							<div class="menu">
								{#each books as b (b.id)}
									<button
										type="button"
										class="menu-item"
										class:on={b.id === header.book_id}
										onclick={() => start(b.id)}
									>
										<span class="menu-title">{b.title}</span>
										<span class="small-caps menu-pos">
											{b.status === 'finished' ? 'Finished' : `Chapter ${b.chapters_read}`}
										</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				<BoundBar
					{header}
					{marks}
					{litIds}
					thinking={sending}
					onpick={(id) => (openCitation = id)}
				/>
			</div>

			<!-- Every interactive target inside is a real button; these handlers are
			     delegated to the container only because the answer HTML is generated. -->
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<!-- svelte-ignore a11y_mouse_events_have_key_events -->
			<div
				class="thread"
				bind:this={threadEl}
				onclick={onThreadClick}
				onmouseover={onThreadOver}
				onmouseup={onThreadMouseUp}
				onscroll={onThreadScroll}
				role="log"
				aria-live="polite"
			>
				{#if movedOn && startedAtLabel}
					<div class="moved">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
							<path d="M12 8v5l3 2" /><circle cx="12" cy="12" r="9" />
						</svg>
						<p>
							You started this at <em>{startedAtLabel}</em> and have read to
							<em>{header.chapter_label}</em> since. Anything you ask now reaches the further mark —
							the answers below still stop where they did.
						</p>
					</div>
				{/if}

				{#if turns.length === 0}
					<div class="opening">
						<p class="lede">
							{header.chapter_position >= header.chapter_count
								? 'The whole book.'
								: `${header.chapter_position} chapters in.`}
						</p>
						<p class="sub">
							Everything up to here is on the table{header.prior_books.length
								? `, including all of ${header.prior_books.map((b) => b.title).join(' and ')}`
								: ''}. Ask anything, or start with one of these.
						</p>
						<div class="suggestions">
							{#each [{ k: 'Pick up the thread', q: 'Catch me up — where does the story stand right now?' }, { k: "Who's who", q: "Remind me who I've met so far" }, { k: 'Motives', q: 'What is each of the main characters actually trying to do?' }, { k: 'Loose ends', q: "What has been set up that hasn't paid off yet?" }] as s (s.q)}
								<button
									type="button"
									class="sug"
									onclick={() => {
										question = s.q;
										submit();
									}}
								>
									<span class="small-caps sug-k">{s.k}</span>
									<span class="sug-q">{s.q}</span>
								</button>
							{/each}
						</div>
					</div>
				{/if}

				{#each turns as t, i (i)}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="turn"
						onmouseenter={() => (hoveredTurn = i)}
						onmouseleave={() => (hoveredTurn = null)}
					>
						<div class="ask">
							<p class="question">{t.question}</p>
						</div>
						{#if t.answer !== undefined}
							<div class="answer">
								<!-- eslint-disable-next-line svelte/no-at-html-tags -->
								{@html renderAnswer(t.answer, t.citations)}
							</div>
							<div class="foot">
								<div class="acts">
									<button
										type="button"
										class="act"
										aria-label="Copy answer"
										onclick={() => navigator.clipboard?.writeText(t.answer ?? '')}
									>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
											<rect x="9" y="9" width="11" height="11" rx="2" />
											<path d="M5 15V5a2 2 0 0 1 2-2h8" />
										</svg>
									</button>
									<button
										type="button"
										class="act"
										aria-label="Ask a follow-up"
										onclick={() => textareaEl?.focus()}
									>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
											<path d="M21 12a8 8 0 0 1-8 8H7l-4 3v-4.6A8 8 0 0 1 11 4h2a8 8 0 0 1 8 8Z" />
										</svg>
									</button>
								</div>
								{#if debugOn && t.debug}
									<p class="mono debug">
										ctx {t.debug.context_tokens} · prompt {t.debug.prompt_tokens ?? '?'} · cached {t
											.debug.cached_tokens ?? 0} · turn ${(t.debug.turn_cost_usd ?? 0).toFixed(4)}
									</p>
								{/if}
							</div>
						{:else if i === turns.length - 1 && sending}
							<p class="pending">Reading everything you've read…</p>
						{/if}
					</div>
				{/each}
			</div>

			<div class="composer">
				<div class="field" class:filled={question.trim().length > 0}>
					<textarea
						bind:this={textareaEl}
						bind:value={question}
						oninput={autoGrow}
						onkeydown={onKeydown}
						placeholder="Ask about what you've read so far…"
						rows="1"
						disabled={sending}
					></textarea>
				</div>
				{#if sending}
					<button type="button" class="send stop" onclick={cancel} aria-label="Stop">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<rect x="7" y="7" width="10" height="10" rx="2" />
						</svg>
					</button>
				{:else}
					<button
						type="button"
						class="send"
						onclick={submit}
						disabled={!question.trim()}
						aria-label="Send"
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
							<path d="M12 19V5M12 5l-6 6M12 5l6 6" />
						</svg>
					</button>
				{/if}
			</div>
			<div class="controls">
				<button
					type="button"
					class="small-caps toggle"
					class:on={debugOn}
					onclick={() => (debugOn = !debugOn)}
				>
					<span class="track"><span class="knob"></span></span>
					Debug
				</button>
				{#if sessionCost > 0}
					<span class="small-caps cost">Session ${sessionCost.toFixed(4)}</span>
				{/if}
				<span class="spacer"></span>
				<span class="hint">
					{sending ? 'Reading… press stop to cancel' : 'Enter to send · Shift+Enter for a new line'}
				</span>
			</div>
		{:else if !loadError}
			<div class="middle">
				<p class="none">
					{books.length === 0
						? 'No book has a reading position yet.'
						: 'Start a conversation from the panel on the left.'}
					{#if books.length === 0}<a href="/">Go to the library →</a>{/if}
				</p>
			</div>
		{/if}

		</div>

		{#if openCitation && header}
			<CitationSheet
				sessionId={header.session_id}
				citationId={openCitation}
				onclose={() => (openCitation = null)}
			/>
		{/if}
	</div>

	<ConversationList
		{groups}
		activeId={conversationId}
		bind:open={listOpen}
		onopen={load}
		onnew={() => header && start(header.book_id)}
		ondelete={remove}
	/>
</div>

{#if peek}
	<div class="peek" style="left: {peek.x}px; top: {peek.y}px;">{peek.text}</div>
{/if}

{#if selection}
	<button
		type="button"
		class="sel-chip small-caps"
		style="left: {selection.x}px; top: {selection.y}px;"
		onclick={askAboutSelection}
	>
		Ask about this
	</button>
{/if}

<style>
	.chat {
		display: flex;
		min-width: 0;
		height: calc(100vh - var(--sp-12) - 2px);
		margin: calc(var(--sp-8) * -1) calc(var(--sp-8) * -1) calc(var(--sp-12) * -1);
	}
	.pane {
		flex: 1;
		min-width: 0;
		display: flex;
		min-height: 0;
		position: relative;
	}
	.convo {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	/* The book's own cover, blurred and bled down behind the header, so a
	   conversation is tinted by the book it belongs to. */
	.wash {
		position: absolute;
		inset: 0;
		overflow: hidden;
		pointer-events: none;
		z-index: -1;
	}
	.wash img {
		position: absolute;
		top: -30%;
		left: -10%;
		width: 120%;
		height: 160%;
		object-fit: cover;
		filter: blur(46px) saturate(1.25);
		opacity: 0.62;
	}
	:root[data-theme='light'] .wash img {
		opacity: 0.34;
	}
	.wash .fade {
		position: absolute;
		inset: 0;
		background: linear-gradient(
			to bottom,
			color-mix(in srgb, var(--ink-surface) 25%, transparent) 0%,
			color-mix(in srgb, var(--ink-surface) 62%, transparent) 58%,
			color-mix(in srgb, var(--ink-surface) 94%, transparent) 100%
		);
	}

	.head {
		position: relative;
		z-index: 2;
		isolation: isolate;
		background: var(--ink-surface);
		padding: var(--sp-6) 34px 18px;
		border-bottom: var(--hairline);
		flex-shrink: 0;
	}
	.head-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-6);
		margin-bottom: 20px;
	}
	.ident {
		display: flex;
		gap: var(--sp-4);
		align-items: flex-start;
		min-width: 0;
	}
	.cover {
		width: 42px;
		height: 63px;
		flex: 0 0 auto;
		border-radius: 1px var(--r-cover) var(--r-cover) 1px;
		overflow: hidden;
		background: var(--ink-bg);
		box-shadow:
			0 8px 18px -6px rgba(0, 0, 0, 0.75),
			inset 2px 0 0 rgba(0, 0, 0, 0.28);
	}
	.cover img,
	.cover .fb {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
		background: var(--ink-bg);
	}
	.titles {
		min-width: 0;
	}
	.switcher {
		position: relative;
		flex-shrink: 0;
	}
	.switch {
		display: flex;
		align-items: center;
		gap: 9px;
		font-size: 10px;
		color: var(--bone-muted);
		border: var(--hairline);
		border-radius: 6px;
		padding: 9px 13px;
		background: color-mix(in srgb, var(--alcove) 70%, transparent);
		cursor: pointer;
		transition: color 0.14s, border-color 0.14s;
	}
	.switch svg {
		width: 12px;
		height: 12px;
	}
	.switch:hover {
		color: var(--bone);
		border-color: var(--brass-dim);
	}
	.menu {
		position: absolute;
		right: 0;
		top: calc(100% + 6px);
		z-index: 30;
		width: 280px;
		max-height: 340px;
		overflow-y: auto;
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: 8px;
		box-shadow: 0 16px 34px -18px rgba(0, 0, 0, 0.9);
		padding: 6px;
	}
	.menu-item {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: 9px 10px;
		border-radius: 5px;
		cursor: pointer;
	}
	.menu-item:hover {
		background: var(--alcove);
	}
	.menu-item.on .menu-title {
		color: var(--brass-text);
	}
	.menu-title {
		display: block;
		font-size: var(--fs-14);
		line-height: 1.35;
		color: var(--bone);
	}
	.menu-pos {
		display: block;
		margin-top: 3px;
		font-size: 9px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
	}
	.series {
		font-size: 10px;
		color: var(--brass-text);
	}
	.titles h1 {
		margin: 5px 0 0;
		font-family: var(--serif-display);
		font-style: italic;
		font-weight: 400;
		font-size: 31px;
		line-height: 1.1;
		color: var(--bone);
	}
	.author {
		display: block;
		margin-top: 3px;
		font-size: var(--fs-13);
		color: var(--bone-muted);
	}

	.thread {
		flex: 1;
		overflow-y: auto;
		padding: 6px 34px 20px;
		min-height: 0;
		scrollbar-width: thin;
	}
	.moved {
		margin: var(--sp-6) 0 0;
		display: flex;
		gap: var(--sp-3);
		align-items: flex-start;
		padding: 13px 16px;
		border: 1px solid var(--brass-dim);
		border-radius: 8px;
		background: color-mix(in srgb, var(--brass) 6%, transparent);
	}
	.moved svg {
		width: 16px;
		height: 16px;
		flex: 0 0 auto;
		margin-top: 2px;
		color: var(--brass-text);
	}
	.moved p {
		margin: 0;
		font-size: 14.5px;
		line-height: 1.6;
		color: var(--bone-muted);
	}
	.moved em {
		color: var(--brass-text);
		font-style: normal;
	}

	.opening {
		padding: var(--sp-12) 0 var(--sp-6);
		max-width: 720px;
	}
	.lede {
		margin: 0 0 10px;
		font-family: var(--serif-display);
		font-style: italic;
		font-size: 34px;
		line-height: 1.25;
		color: var(--bone);
	}
	.sub {
		margin: 0 0 30px;
		font-size: var(--fs-16);
		line-height: 1.7;
		color: var(--bone-muted);
		max-width: 560px;
	}
	.suggestions {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--sp-3);
		max-width: 660px;
	}
	.sug {
		text-align: left;
		border: var(--hairline);
		border-radius: 10px;
		padding: 16px 17px;
		background: var(--alcove);
		cursor: pointer;
		transition:
			border-color 0.16s ease,
			background 0.16s ease,
			transform 0.16s ease;
	}
	.sug:hover {
		border-color: var(--brass-dim);
		transform: translateY(-2px);
	}
	.sug-k {
		display: block;
		font-size: 9px;
		letter-spacing: 0.16em;
		color: var(--brass-text);
		margin-bottom: 9px;
	}
	.sug-q {
		display: block;
		font-size: var(--fs-16);
		line-height: 1.45;
		color: var(--bone);
	}

	.turn {
		padding: var(--sp-6) 0 0;
	}
	.ask {
		display: flex;
		justify-content: flex-end;
		margin-bottom: 20px;
	}
	/* A bubble, but in the app's own materials: brass-tinted, with the accent
	   at the start of the line rather than a border all the way round. */
	.question {
		margin: 0;
		max-width: 460px;
		padding: 12px 17px;
		border-radius: var(--r-card) var(--r-card) 4px var(--r-card);
		border-left: 2px solid var(--brass);
		background: color-mix(in srgb, var(--brass) 11%, var(--alcove));
		font-size: 16.5px;
		line-height: 1.5;
		color: var(--bone);
	}
	.answer {
		max-width: 640px;
		font-size: 17px;
		line-height: 1.78;
		color: var(--bone);
	}
	.answer :global(p) {
		margin: 0 0 17px;
	}
	.answer :global(p:last-child) {
		margin-bottom: 0;
	}
	.answer :global(.citation-chip) {
		display: inline-block;
		vertical-align: super;
		font-family: var(--sans-caps);
		font-size: 10px;
		line-height: 1;
		background: color-mix(in srgb, var(--brass) 16%, transparent);
		color: var(--brass-text);
		border: none;
		border-radius: 3px;
		padding: 2px 4px;
		margin: 0 1px;
		cursor: pointer;
		transition:
			background 0.14s,
			color 0.14s;
	}
	.answer :global(.citation-chip:hover),
	.answer :global(.citation-chip.active) {
		background: var(--brass);
		color: var(--ink-bg);
	}
	:root[data-theme='light'] .answer :global(.citation-chip:hover),
	:root[data-theme='light'] .answer :global(.citation-chip.active) {
		color: var(--ink-surface);
	}

	.foot {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
		margin-top: 14px;
		max-width: 640px;
	}
	.acts {
		display: flex;
		gap: 2px;
		margin-left: -6px;
		opacity: 0;
		transition: opacity 0.18s ease;
	}
	.turn:hover .acts,
	.acts:focus-within {
		opacity: 1;
	}
	.act {
		width: 27px;
		height: 27px;
		border: none;
		border-radius: 6px;
		background: none;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--bone-faint);
		cursor: pointer;
		transition:
			color 0.14s,
			background 0.14s;
	}
	.act svg {
		width: 14px;
		height: 14px;
	}
	.act:hover {
		color: var(--brass-text);
		background: var(--ink-bg);
	}
	.debug {
		margin: 0;
		font-family: var(--mono);
		font-size: 11px;
		color: var(--bone-faint);
	}
	.pending {
		margin: 0;
		font-style: italic;
		font-size: var(--fs-16);
		color: var(--brass-text);
		animation: breathe 1.7s ease-in-out infinite;
	}
	@keyframes breathe {
		0%,
		100% {
			opacity: 0.45;
		}
		50% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pending {
			animation: none;
		}
	}

	.composer {
		flex-shrink: 0;
		display: flex;
		gap: 14px;
		align-items: flex-end;
		border-top: var(--hairline);
		padding: var(--sp-4) 34px 0;
	}
	.field {
		flex: 1;
		background: var(--alcove);
		border: var(--hairline);
		border-radius: 10px;
		padding: 12px 16px;
		transition:
			border-color 0.16s ease,
			box-shadow 0.16s ease;
	}
	.field.filled {
		border-color: var(--brass-dim);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--brass) 7%, transparent);
	}
	.field textarea {
		display: block;
		width: 100%;
		background: none;
		border: none;
		color: var(--bone);
		font-family: var(--serif-body);
		font-size: 17px;
		line-height: 1.55;
		resize: none;
		max-height: 200px;
		outline: none;
	}
	.field textarea::placeholder {
		font-style: italic;
		color: var(--bone-faint);
	}
	.send {
		flex: 0 0 auto;
		width: 46px;
		height: 46px;
		border: none;
		border-radius: 50%;
		background: var(--brass);
		color: var(--ink-bg);
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		transition:
			transform 0.14s ease,
			background 0.14s ease,
			opacity 0.14s ease;
	}
	.send svg {
		width: 19px;
		height: 19px;
	}
	.send:hover:not(:disabled) {
		transform: translateY(-1px);
		background: var(--quote);
	}
	.send:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.send.stop {
		background: var(--oxblood);
		color: var(--bone);
	}
	:root[data-theme='light'] .send {
		color: var(--ink-surface);
	}

	.controls {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		gap: var(--sp-6);
		padding: 13px 34px 18px;
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		background: none;
		border: none;
		padding: 0;
		font-size: 9.5px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
		cursor: pointer;
	}
	.toggle.on {
		color: var(--brass-text);
	}
	.toggle .track {
		width: 20px;
		height: 11px;
		border-radius: 6px;
		background: var(--ink-hairline);
		position: relative;
		display: inline-block;
		transition: background 0.16s ease;
	}
	.toggle.on .track {
		background: var(--brass-dim);
	}
	.toggle .knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--bone-faint);
		transition:
			left 0.16s ease,
			background 0.16s ease;
	}
	.toggle.on .knob {
		left: 11px;
		background: var(--brass);
	}
	.cost {
		font-size: 9.5px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
	}
	.spacer {
		flex: 1;
	}
	.hint {
		font-size: 12.5px;
		font-style: italic;
		color: var(--bone-faint);
	}

	.middle {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--sp-8);
	}
	.none {
		font-style: italic;
		color: var(--bone-muted);
		text-align: center;
	}
	.none a {
		color: var(--brass);
	}
	.error {
		margin: var(--sp-6) 34px 0;
		color: var(--oxblood);
	}

	.peek {
		position: fixed;
		transform: translateY(calc(-100% - 10px));
		width: 268px;
		padding: 10px 12px;
		border: 1px solid var(--ink-hairline);
		border-radius: 7px;
		background: var(--alcove);
		box-shadow: 0 12px 26px -12px rgba(0, 0, 0, 0.9);
		font-size: var(--fs-13);
		font-style: italic;
		line-height: 1.5;
		color: var(--bone-muted);
		pointer-events: none;
		z-index: 80;
		display: -webkit-box;
		-webkit-line-clamp: 4;
		line-clamp: 4;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.sel-chip {
		position: fixed;
		transform: translate(-50%, calc(-100% - 8px));
		white-space: nowrap;
		padding: 6px 11px;
		border: none;
		border-radius: 6px;
		background: var(--brass);
		color: var(--ink-bg);
		font-size: 9.5px;
		letter-spacing: 0.16em;
		cursor: pointer;
		z-index: 80;
	}
	:root[data-theme='light'] .sel-chip {
		color: var(--ink-surface);
	}

	@media (max-width: 900px) {
		.chat {
			height: auto;
			min-height: 70vh;
		}
	}
</style>
