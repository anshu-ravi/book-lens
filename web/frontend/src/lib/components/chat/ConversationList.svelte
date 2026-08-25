<script lang="ts">
	import type { ConversationGroup } from '$lib/types';
	import { formatRelative } from '$lib/utils/format-date';

	let {
		groups,
		activeId,
		open = $bindable(true),
		onopen,
		onnew,
		ondelete,
	}: {
		groups: ConversationGroup[];
		activeId: string | null;
		open?: boolean;
		onopen: (conversationId: string) => void;
		/** Starts a fresh conversation on whichever book the screen is already on. */
		onnew: () => void;
		ondelete: (conversationId: string) => void;
	} = $props();

	const total = $derived(groups.reduce((n, g) => n + g.conversations.length, 0));
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
					<path d="M10 6l6 6-6 6" />
				</svg>
			</button>
		</div>

		<div class="new-wrap">
			<button type="button" class="new small-caps" onclick={onnew}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
					<path d="M12 5v14M5 12h14" />
				</svg>
				New conversation
			</button>
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
						<button
							type="button"
							class="icon"
							onclick={() => ondelete(conv.id)}
							aria-label="Delete conversation"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
								<path d="M5 7h14M10 7V5h4v2M8 7l1 12h6l1-12" />
							</svg>
						</button>
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
				<path d="M14 6l-6 6 6 6" />
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
		border-left: var(--hairline);
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
	.new-wrap {
		padding: 0 14px 14px;
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
		border-right: 2px solid transparent;
		transition: background 0.14s;
	}
	.row:hover {
		background: var(--ink-surface);
	}
	.row.on {
		border-right-color: var(--brass);
		background: var(--ink-surface);
	}
	.row .icon {
		opacity: 0;
		margin-top: 9px;
		margin-right: 4px;
	}
	.row:hover .icon,
	.row .icon:focus-visible {
		opacity: 1;
	}
	.row .icon:hover {
		color: var(--oxblood);
	}
	.item {
		flex: 1;
		min-width: 0;
		text-align: left;
		background: none;
		border: none;
		padding: 10px 4px 10px 10px;
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
		border-left: var(--hairline);
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
