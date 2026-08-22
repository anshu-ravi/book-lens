<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import type { UnifiedEntry } from '$lib/types';
	import { formatDateLong } from '$lib/utils/format-date';
	import { htmlToParagraphs } from '$lib/utils/strip-html';

	let {
		entry,
		onclose,
		onedit,
	}: {
		entry: UnifiedEntry;
		onclose: () => void;
		onedit: (focus: 'details' | 'reading') => void;
	} = $props();

	const descriptionParagraphs = $derived(entry.description ? htmlToParagraphs(entry.description) : []);
	const stars = $derived(
		entry.user_rating ? Array.from({ length: 5 }, (_, i) => i < entry.user_rating!) : null,
	);

	let coverFailed = $state(false);
	let modalEl: HTMLDivElement | undefined = $state();
	let previouslyFocused: HTMLElement | null = null;

	onMount(() => {
		previouslyFocused = document.activeElement as HTMLElement | null;
		document.body.style.overflow = 'hidden';
		tick().then(() => modalEl?.focus());
		return () => {
			document.body.style.overflow = '';
			previouslyFocused?.focus();
		};
	});

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}

	function askAbout() {
		if (entry.book_id) goto(`/chat?book=${encodeURIComponent(entry.book_id)}`);
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay">
	<button type="button" class="overlay-dismiss" aria-label="Close" onclick={onclose}></button>
	<div
		class="modal"
		role="dialog"
		aria-modal="true"
		aria-label={entry.title}
		tabindex="-1"
		bind:this={modalEl}
	>
		<button type="button" class="modal-close" aria-label="Close" onclick={onclose}>
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M3 3l10 10M13 3 3 13" />
			</svg>
		</button>
		<div class="modal-body">
			<div class="cover-col">
				{#if entry.cover && !coverFailed}
					<img class="cover" src={entry.cover} alt="" onerror={() => (coverFailed = true)} />
				{:else}
					<div class="cover cover-fallback">
						<div class="fallback-title">{entry.display_title}</div>
						<div class="fallback-author small-caps">{entry.author}</div>
					</div>
				{/if}
			</div>

			<div class="details-col">
				<h2 class="title">{entry.display_title}</h2>
				<p class="author">by {entry.author}</p>
				{#if entry.series}
					<p class="series-line small-caps">
						{entry.series}{entry.series_number !== null ? ` · Volume ${entry.series_number}` : ''}
					</p>
				{/if}

				{#if stars || entry.average_rating !== null}
					<div class="ratings">
						{#if stars}
							<div class="rating-row">
								<span class="stars" aria-hidden="true">
									{#each stars as filled}
										<span class="star" class:filled>★</span>
									{/each}
								</span>
								<span class="rating-label small-caps">your rating</span>
							</div>
						{/if}
						{#if entry.average_rating !== null}
							<div class="rating-row">
								<span class="avg-rating">{entry.average_rating.toFixed(2)}</span>
								<span class="rating-label small-caps">goodreads average</span>
							</div>
						{/if}
					</div>
				{/if}

				{#if entry.genres.length > 0}
					<div class="chips">
						{#each entry.genres as genre (genre)}
							<span class="chip small-caps">{genre}</span>
						{/each}
					</div>
				{/if}

				<dl class="facts">
					{#if entry.num_pages !== null}
						<div class="fact"><dt class="small-caps">Pages</dt><dd>{entry.num_pages}</dd></div>
					{/if}
					{#if entry.date_added}
						<div class="fact"><dt class="small-caps">Added</dt><dd>{formatDateLong(entry.date_added)}</dd></div>
					{/if}
					{#if entry.date_started}
						<div class="fact"><dt class="small-caps">Started</dt><dd>{formatDateLong(entry.date_started)}</dd></div>
					{/if}
					{#if entry.date_read}
						<div class="fact"><dt class="small-caps">Finished</dt><dd>{formatDateLong(entry.date_read)}</dd></div>
					{/if}
				</dl>

				{#if descriptionParagraphs.length > 0}
					<div class="section">
						<span class="section-heading small-caps">Description</span>
						{#each descriptionParagraphs as para}
							<p class="description-text">{para}</p>
						{/each}
					</div>
				{/if}

				{#if entry.goodreads_url}
					<a class="goodreads-link small-caps" href={entry.goodreads_url} target="_blank" rel="noopener noreferrer">
						View on Goodreads →
					</a>
				{/if}

				<div class="actions">
					{#if entry.askable}
						<button type="button" class="btn-primary small-caps" onclick={askAbout}>
							Ask about this book
						</button>
						<button type="button" class="btn-ghost small-caps" onclick={() => onedit('reading')}>
							Set reading position
						</button>
						<button type="button" class="btn-ghost small-caps" onclick={() => onedit('details')}>
							Edit details
						</button>
					{:else}
						<a class="btn-ghost small-caps" href="/upload">Add EPUB</a>
					{/if}
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: var(--sp-4);
	}
	.overlay-dismiss {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		border: none;
		padding: 0;
		background: color-mix(in srgb, var(--ink-bg) 80%, transparent);
		cursor: default;
	}
	.modal {
		position: relative;
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-cover);
		padding: var(--sp-8);
		width: min(880px, 100%);
		max-height: 85vh;
		overflow-y: auto;
	}
	.modal:focus-visible {
		outline: none;
	}
	.modal-close {
		position: absolute;
		top: var(--sp-4);
		right: var(--sp-4);
		background: none;
		border: none;
		padding: var(--sp-1);
		cursor: pointer;
		color: var(--bone-muted);
		transition: color 0.15s;
	}
	.modal-close:hover,
	.modal-close:focus-visible {
		color: var(--brass);
	}
	.modal-body {
		display: flex;
		gap: var(--sp-8);
	}
	.cover-col {
		flex-shrink: 0;
		width: 220px;
	}
	.cover {
		width: 100%;
		border-radius: var(--r-cover);
		display: block;
	}
	.cover-fallback {
		aspect-ratio: 2 / 3;
		background: var(--ink-bg);
		border: var(--hairline);
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		padding: var(--sp-4);
		gap: var(--sp-2);
	}
	.fallback-title {
		font-family: var(--serif-display);
		font-style: italic;
		color: var(--bone);
		font-size: var(--fs-16);
	}
	.fallback-author {
		color: var(--bone-muted);
	}
	.details-col {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}
	.title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-28);
		color: var(--bone);
		margin: 0;
		padding-right: var(--sp-8);
	}
	.author {
		font-family: var(--serif-body);
		color: var(--bone-muted);
		margin: calc(-1 * var(--sp-2)) 0 0;
	}
	.series-line {
		color: var(--brass-text);
		margin: calc(-1 * var(--sp-2)) 0 0;
	}
	.ratings {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.rating-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}
	.stars {
		letter-spacing: 2px;
	}
	.star {
		color: var(--brass-dim);
	}
	.star.filled {
		color: var(--brass);
	}
	.avg-rating {
		font-family: var(--serif-display);
		color: var(--bone);
	}
	.rating-label {
		color: var(--bone-faint);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}
	.chip {
		display: inline-block;
		padding: 2px 6px;
		border-radius: var(--r-chip);
		background: color-mix(in srgb, var(--bone-muted) 15%, transparent);
		color: var(--bone-muted);
		font-size: 10px;
	}
	.facts {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-4) var(--sp-8);
		margin: 0;
	}
	.fact {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.fact dt {
		color: var(--bone-faint);
	}
	.fact dd {
		margin: 0;
		color: var(--bone);
		font-family: var(--serif-body);
	}
	.section {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		padding-top: var(--sp-2);
		border-top: var(--hairline);
	}
	.section-heading {
		color: var(--bone-muted);
	}
	.description-text {
		font-family: var(--serif-body);
		color: var(--bone);
		line-height: 1.5;
		margin: 0;
	}
	.goodreads-link {
		color: var(--brass);
		text-decoration: none;
		align-self: flex-start;
	}
	.goodreads-link:hover {
		text-decoration: underline;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-3);
		margin-top: var(--sp-2);
		padding-top: var(--sp-4);
		border-top: var(--hairline);
	}
	.btn-primary,
	.btn-ghost {
		padding: var(--sp-2) var(--sp-4);
		border-radius: var(--r-chip);
		cursor: pointer;
		text-decoration: none;
		display: inline-block;
	}
	.btn-primary {
		background: var(--brass);
		border: 1px solid var(--brass);
		color: var(--ink-bg);
	}
	:global(:root[data-theme='light']) .btn-primary {
		color: var(--bone);
	}
	.btn-ghost {
		background: none;
		border: var(--hairline);
		color: var(--bone-muted);
	}
	.btn-ghost:hover {
		color: var(--brass-text);
		border-color: var(--brass);
	}
	@media (max-width: 700px) {
		.modal-body {
			flex-direction: column;
		}
		.cover-col {
			width: 160px;
		}
	}
</style>
