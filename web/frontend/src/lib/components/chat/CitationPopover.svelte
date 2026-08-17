<script lang="ts">
	import { onMount } from 'svelte';
	import { getCitationWindow, ApiError } from '$lib/api';
	import type { CitationParagraph } from '$lib/types';

	let {
		sessionId,
		citationId,
		anchor,
		onclose,
	}: {
		sessionId: string;
		citationId: string;
		anchor: DOMRect;
		onclose: () => void;
	} = $props();

	const WIDTH = 380;
	const MARGIN = 16;

	let paragraphs = $state<CitationParagraph[] | null>(null);
	let error = $state('');

	onMount(async () => {
		try {
			const res = await getCitationWindow(sessionId, citationId);
			paragraphs = res.paragraphs;
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not load that passage.';
		}
	});

	const left = $derived.by(() => {
		const vw = window.innerWidth;
		let l = anchor.right + MARGIN;
		if (l + WIDTH + MARGIN > vw) {
			l = anchor.left - WIDTH - MARGIN;
		}
		return Math.max(MARGIN, Math.min(l, vw - WIDTH - MARGIN));
	});

	const top = $derived.by(() => {
		const vh = window.innerHeight;
		const maxHeight = Math.min(vh * 0.6, 520);
		let t = anchor.top;
		return Math.max(MARGIN, Math.min(t, vh - maxHeight - MARGIN));
	});
</script>

<div
	class="citation-popover"
	role="dialog"
	aria-label="Cited passage"
	style="left: {left}px; top: {top}px;"
>
	<div class="drawer-head">
		<span class="small-caps">Cited passage</span>
		<button class="close-btn" onclick={onclose} aria-label="Close">×</button>
	</div>
	{#if error}
		<p class="error">{error}</p>
	{:else if paragraphs === null}
		<p class="loading">Loading…</p>
	{:else}
		{#each paragraphs as p (p.citation_id)}
			<div class="para" class:target={p.citation_id === citationId}>
				<span class="para-id mono">{p.citation_id}</span>
				<span class="para-chapter small-caps">{p.chapter}</span>
				<p class="para-text">{p.text}</p>
			</div>
		{/each}
	{/if}
</div>

<style>
	.citation-popover {
		position: fixed;
		width: 380px;
		max-height: min(60vh, 520px);
		overflow-y: auto;
		border: var(--hairline);
		border-radius: var(--r-cover);
		padding: var(--sp-4);
		background: var(--ink-surface);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
		z-index: 90;
	}
	.drawer-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--sp-4);
	}
	.drawer-head .small-caps {
		color: var(--brass);
	}
	.close-btn {
		background: none;
		border: none;
		color: var(--bone-muted);
		font-size: var(--fs-18);
		cursor: pointer;
		line-height: 1;
		padding: 0 var(--sp-2);
	}
	.para {
		padding: var(--sp-3) 0;
		border-top: 1px solid var(--ink-hairline);
	}
	.para:first-child {
		border-top: none;
	}
	.para.target {
		background: color-mix(in srgb, var(--brass) 8%, transparent);
	}
	.para-id {
		color: var(--brass);
		font-size: var(--fs-12);
		margin-right: var(--sp-3);
	}
	.para-chapter {
		color: var(--bone-muted);
	}
	.para-text {
		margin: var(--sp-2) 0 0;
		color: var(--bone);
		line-height: 1.6;
	}
	.error,
	.loading {
		font-style: italic;
		color: var(--bone-muted);
	}
</style>
