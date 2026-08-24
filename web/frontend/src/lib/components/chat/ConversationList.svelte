<script lang="ts">
	import type { Book, ConversationGroup } from '$lib/types';
	import { formatRelative } from '$lib/utils/format-date';

	let {
		groups,
		books,
		activeId,
		open = $bindable(true),
		onopen,
		onnew,
		ondelete,
	}: {
		groups: ConversationGroup[];
		books: Book[];
		activeId: string | null;
		open?: boolean;
		onopen: (conversationId: string) => void;
		onnew: (bookId: string) => void;
		ondelete: (conversationId: string) => void;
	} = $props();

	let picking = $state(false);
	let confirming = $state<string | null>(null);

	const total = $derived(groups.reduce((n, g) => n + g.conversations.length, 0));

	function startOn(bookId: string) {
		picking = false;
		onnew(bookId);
	}
</script>

{#if open}
	<aside class="panel">
		<div class="head">
			<span class="small-caps">Conversations</span>
			<button
				type="button"
				class="icon"
				onclick={() => (open = false)}
				aria-label="Collapse conversations"
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
					<path d="M14 6l-6 6 6 6" />
				</svg>
			</button>
		</div>

		<div class="new-wrap">
			<button type="button" class="new small-caps" onclick={() => (picking = !picking)}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
					<path d="M12 5v14M5 12h14" />
				</svg>
				New conversation
			</button>
			{#if picking}
				<div class="picker">
					{#if books.length === 0}
						<p class="empty-pick">
							No book has a reading position yet. <a href="/">Set one in the library →</a>
						</p>
					{:else}
						{#each books as book (book.id)}
							<button type="button" class="pick" onclick={() => startOn(book.id)}>
								<span class="pick-title">{book.title}</span>
								<span class="small-caps pick-pos">Chapter {book.chapters_read}</span>
							</button>
						{/each}
					{/if}
				</div>
			{/if}
		</div>

		<div class="list">
			{#if total === 0}
				<p class="empty">Nothing saved yet. Every conversation you start is kept here, under its
					book.</p>
			{/if}
			{#each groups as group (group.book_id)}
				<div class="group-head">
					<span class="group-title">{group.book_title}</span>
					<span class="rule"></span>
				</div>
				{#each group.conversations as conv (conv.id)}
					<div class="row" class:on={conv.id === activeId}>
						<button type="button" class="item" onclick={() => onopen(conv.id)}>
							<span class="q">{conv.title || 'Untitled conversation'}</span>
							<span class="small-caps meta">
								{conv.chapter_label || `Chapter ${conv.chapter_idx + 1}`} ·
								{formatRelative(conv.updated_at)} ·
								{conv.turn_count}
								{conv.turn_count === 1 ? 'turn' : 'turns'}
							</span>
						</button>
						{#if confirming === conv.id}
							<button
								type="button"
								class="icon danger"
								onclick={() => {
									confirming = null;
									ondelete(conv.id);
								}}
								aria-label="Confirm delete"
							>
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
									<path d="M5 12.5l4.5 4.5L19 7.5" />
								</svg>
							</button>
						{:else}
							<button
								type="button"
								class="icon"
								onclick={() => (confirming = conv.id)}
								aria-label="Delete conversation"
							>
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
									<path d="M5 7h14M10 7V5h4v2M8 7l1 12h6l1-12" />
								</svg>
							</button>
						{/if}
					</div>
				{/each}
			{/each}
		</div>
	</aside>
{:else}
	<aside class="spine">
		<button
			type="button"
			class="icon"
			onclick={() => (open = true)}
			aria-label="Expand conversations"
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
				<path d="M10 6l6 6-6 6" />
			</svg>
		</button>
		<div class="dashes">
			{#each groups.flatMap((g) => g.conversations).slice(0, 8) as conv (conv.id)}
				<span class="dash" class:on={conv.id === activeId}></span>
			{/each}
		</div>
		{#if total > 0}
			<span class="small-caps vert">{total} {total === 1 ? 'conversation' : 'conversations'}</span>
		{/if}
	</aside>
{/if}

<style>
	.panel {
		width: 268px;
		flex: 0 0 268px;
		border-right: var(--hairline);
		background: var(--alcove);
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.head {
		padding: var(--sp-6) 18px 14px;
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.head .small-caps {
		font-size: 10px;
		color: var(--bone-faint);
	}
	.icon {
		background: none;
		border: none;
		padding: 4px;
		display: flex;
		color: var(--bone-faint);
		cursor: pointer;
		border-radius: var(--r-chip);
		flex-shrink: 0;
		transition: color 0.14s;
	}
	.icon svg {
		width: 15px;
		height: 15px;
	}
	.icon:hover {
		color: var(--bone);
	}
	.icon.danger {
		color: var(--oxblood);
	}
	.new-wrap {
		padding: 0 14px 14px;
		position: relative;
	}
	.new {
		width: 100%;
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		justify-content: center;
		font-size: 10px;
		color: var(--brass-text);
		border: 1px solid var(--brass-dim);
		border-radius: 6px;
		padding: 10px 12px;
		background: transparent;
		cursor: pointer;
		transition:
			border-color 0.14s,
			background 0.14s;
	}
	.new svg {
		width: 13px;
		height: 13px;
	}
	.new:hover {
		border-color: var(--brass);
		background: color-mix(in srgb, var(--brass) 8%, transparent);
	}
	.picker {
		position: absolute;
		left: 14px;
		right: 14px;
		top: calc(100% - 6px);
		z-index: 20;
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: 8px;
		box-shadow: 0 16px 34px -18px rgba(0, 0, 0, 0.9);
		padding: 6px;
		max-height: 320px;
		overflow-y: auto;
	}
	.pick {
		display: block;
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		padding: 9px 10px;
		border-radius: 5px;
		cursor: pointer;
	}
	.pick:hover {
		background: var(--alcove);
	}
	.pick-title {
		display: block;
		font-size: var(--fs-14);
		color: var(--bone);
		line-height: 1.35;
	}
	.pick-pos {
		display: block;
		margin-top: 3px;
		font-size: 9px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
	}
	.empty-pick {
		margin: 0;
		padding: 10px;
		font-size: var(--fs-13);
		font-style: italic;
		color: var(--bone-muted);
	}
	.empty-pick a {
		color: var(--brass);
	}
	.list {
		flex: 1;
		overflow-y: auto;
		padding: 4px 8px 20px;
		scrollbar-width: thin;
	}
	.empty {
		margin: 10px;
		font-size: var(--fs-13);
		font-style: italic;
		line-height: 1.6;
		color: var(--bone-faint);
	}
	.group-head {
		padding: 14px 10px 6px;
		display: flex;
		align-items: baseline;
		gap: var(--sp-2);
	}
	.group-title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: 15px;
		color: var(--brass-text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rule {
		flex: 1;
		height: 1px;
		background: var(--ink-hairline);
	}
	.row {
		display: flex;
		align-items: flex-start;
		gap: 2px;
		border-radius: 6px;
		border-left: 2px solid transparent;
		transition: background 0.14s;
	}
	.row:hover {
		background: var(--ink-surface);
	}
	.row.on {
		border-left-color: var(--brass);
		background: var(--ink-surface);
	}
	.row .icon {
		opacity: 0;
		margin-top: 9px;
		margin-right: 4px;
	}
	.row:hover .icon,
	.row .icon.danger {
		opacity: 1;
	}
	.item {
		flex: 1;
		min-width: 0;
		text-align: left;
		background: none;
		border: none;
		padding: 10px 4px 10px 12px;
		cursor: pointer;
	}
	.q {
		display: block;
		font-size: 14.5px;
		line-height: 1.42;
		color: var(--bone-muted);
	}
	.row.on .q {
		color: var(--bone);
	}
	.meta {
		display: block;
		margin-top: 6px;
		font-size: 9.5px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
	}

	.spine {
		width: 54px;
		flex: 0 0 54px;
		border-right: var(--hairline);
		background: var(--alcove);
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 18px 0;
		gap: 22px;
	}
	.spine .icon svg {
		width: 16px;
		height: 16px;
	}
	.dashes {
		display: flex;
		flex-direction: column;
		gap: 7px;
		align-items: center;
	}
	.dash {
		width: 18px;
		height: 2px;
		background: var(--brass-dim);
	}
	.dash.on {
		background: var(--brass);
	}
	.vert {
		font-size: 9.5px;
		color: var(--bone-faint);
		writing-mode: vertical-rl;
		letter-spacing: 0.22em;
	}
</style>
