<script lang="ts">
	import { getCitationWindow, ApiError } from '$lib/api';
	import type { CitationParagraph } from '$lib/types';

	let {
		sessionId,
		citationId,
		onclose,
	}: {
		sessionId: string;
		citationId: string;
		onclose: () => void;
	} = $props();

	let paragraphs = $state<CitationParagraph[] | null>(null);
	let error = $state('');

	// Re-runs when the reader clicks a different chip while the sheet is open.
	$effect(() => {
		const id = citationId;
		const sid = sessionId;
		paragraphs = null;
		error = '';
		getCitationWindow(sid, id)
			.then((res) => {
				if (id === citationId) paragraphs = res.paragraphs;
			})
			.catch((e) => {
				if (id === citationId) {
					error = e instanceof ApiError ? e.detail : 'Could not load that passage.';
				}
			});
	});

	const chapter = $derived(
		paragraphs?.find((p) => p.citation_id === citationId)?.chapter ?? '',
	);
</script>

<div class="sheet" role="dialog" aria-label="Cited passage">
	<div class="head">
		<div>
			<span class="small-caps kicker">Cited passage</span>
			{#if chapter}
				<p class="chapter">{chapter}</p>
			{/if}
		</div>
		<button type="button" class="close" onclick={onclose} aria-label="Close">
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
				<path d="M6 6l12 12M18 6L6 18" />
			</svg>
		</button>
	</div>

	<div class="body">
		{#if error}
			<p class="quiet">{error}</p>
		{:else if paragraphs === null}
			<p class="quiet">Finding it…</p>
		{:else}
			{#each paragraphs as p (p.citation_id)}
				{#if p.citation_id === citationId}
					<div class="target">
						<p>{p.text}</p>
						<span class="mono id">{p.citation_id}</span>
					</div>
				{:else}
					<p class="around">{p.text}</p>
				{/if}
			{/each}
		{/if}
	</div>
</div>

<style>
	/* Wide enough and the sheet takes its own column, so the answer it annotates
	   stays fully readable beside it. Narrower, it overlays rather than
	   squeezing the prose into an unreadable measure. */
	.sheet {
		position: absolute;
		top: 0;
		right: 0;
		bottom: 0;
		width: 356px;
		background: var(--alcove);
		border-left: var(--hairline);
		box-shadow: -22px 0 44px -26px rgba(0, 0, 0, 0.85);
		display: flex;
		flex-direction: column;
		z-index: 40;
	}
	@media (min-width: 1440px) {
		.sheet {
			position: static;
			flex: 0 0 356px;
		}
	}
	:root[data-theme='light'] .sheet {
		box-shadow: -22px 0 44px -30px rgba(90, 72, 48, 0.6);
	}
	.head {
		padding: var(--sp-6) var(--sp-6) 14px;
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-3);
		border-bottom: var(--hairline);
	}
	.kicker {
		font-size: 9.5px;
		letter-spacing: 0.16em;
		color: var(--brass);
	}
	.chapter {
		margin: 5px 0 0;
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone);
	}
	.close {
		background: none;
		border: none;
		padding: 4px;
		display: flex;
		color: var(--bone-faint);
		cursor: pointer;
		flex-shrink: 0;
	}
	.close svg {
		width: 16px;
		height: 16px;
	}
	.close:hover {
		color: var(--bone);
	}
	.body {
		flex: 1;
		overflow-y: auto;
		padding: 18px var(--sp-6) var(--sp-6);
	}
	.around {
		margin: 0 0 16px;
		font-size: 15px;
		line-height: 1.72;
		color: var(--bone-faint);
	}
	.target {
		border-left: 2px solid var(--brass);
		padding: 4px 0 4px 15px;
		margin: 0 0 16px;
		background: color-mix(in srgb, var(--brass) 5%, transparent);
	}
	.target p {
		margin: 0;
		font-size: 15.5px;
		line-height: 1.72;
		color: var(--bone);
	}
	.id {
		display: block;
		margin-top: 10px;
		font-family: var(--mono);
		font-size: 10.5px;
		color: var(--brass);
	}
	.quiet {
		font-style: italic;
		color: var(--bone-muted);
	}
</style>
