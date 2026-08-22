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
		escapeEnabled = true,
	}: {
		entry: UnifiedEntry;
		onclose: () => void;
		onedit: (focus: 'details' | 'reading') => void;
		escapeEnabled?: boolean;
	} = $props();

	const descriptionParagraphs = $derived(entry.description ? htmlToParagraphs(entry.description) : []);
	const collapsible = $derived(descriptionParagraphs.length > 8);
	let expanded = $state(false);
	const visibleParagraphs = $derived(
		collapsible && !expanded ? descriptionParagraphs.slice(0, 8) : descriptionParagraphs,
	);

	const stars = $derived(
		entry.user_rating ? Array.from({ length: 5 }, (_, i) => i < entry.user_rating!) : null,
	);

	let coverFailed = $state(false);
	const hasCoverBackdrop = $derived(!!entry.cover && !coverFailed);

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
		if (!escapeEnabled) return;
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

		<div class="header-band" class:with-cover={hasCoverBackdrop}>
			{#if hasCoverBackdrop}
				<div class="band-bg" style="background-image: url({entry.cover})"></div>
				<div class="band-scrim"></div>
			{/if}
			<div class="band-content">
				<h2 class="band-title">{entry.display_title}</h2>
				<p class="band-author">by {entry.author}</p>
				{#if entry.series}
					<p class="band-series small-caps">
						{entry.series}{entry.series_number !== null ? ` · Volume ${entry.series_number}` : ''}
					</p>
				{/if}
			</div>
		</div>

		<div class="modal-content-pad">
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

					<div class="action-stack">
						{#if entry.askable}
							<button type="button" class="btn-primary small-caps" onclick={askAbout}>
								Ask about this book
							</button>
							<button type="button" class="btn-secondary small-caps" onclick={() => onedit('reading')}>
								Update your status
							</button>
						{:else}
							<a class="btn-primary small-caps" href="/upload">Upload EPUB</a>
						{/if}
						<button type="button" class="btn-secondary small-caps" onclick={() => onedit('details')}>
							Edit details
						</button>
					</div>

					{#if entry.goodreads_url}
						<a
							class="link-external small-caps"
							href={entry.goodreads_url}
							target="_blank"
							rel="noopener noreferrer"
							aria-label="View on Goodreads"
							title="View on Goodreads"
						>
							Goodreads <span aria-hidden="true">↗</span>
						</a>
					{/if}
				</div>

				<div class="details-col">
					{#if stars || entry.average_rating !== null}
						<div class="ratings-row">
							{#if stars}
								<span class="stars" aria-hidden="true">
									{#each stars as filled}
										<span class="star" class:filled>★</span>
									{/each}
								</span>
								<span class="rating-label small-caps">your rating</span>
							{/if}
							{#if stars && entry.average_rating !== null}
								<span class="ratings-divider"></span>
							{/if}
							{#if entry.average_rating !== null}
								<span class="avg-rating">{entry.average_rating.toFixed(2)}</span>
								<span class="rating-label small-caps">goodreads average</span>
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

					{#if entry.num_pages !== null || entry.date_added || entry.date_started || entry.date_read}
						<dl class="facts">
							{#if entry.num_pages !== null}
								<div class="fact">
									<dt class="fact-label small-caps">Pages</dt>
									<dd class="fact-value">{entry.num_pages}</dd>
								</div>
							{/if}
							{#if entry.date_added}
								<div class="fact">
									<dt class="fact-label small-caps">Added</dt>
									<dd class="fact-value">{formatDateLong(entry.date_added)}</dd>
								</div>
							{/if}
							{#if entry.date_started}
								<div class="fact">
									<dt class="fact-label small-caps">Started</dt>
									<dd class="fact-value">{formatDateLong(entry.date_started)}</dd>
								</div>
							{/if}
							{#if entry.date_read}
								<div class="fact">
									<dt class="fact-label small-caps">Finished</dt>
									<dd class="fact-value">{formatDateLong(entry.date_read)}</dd>
								</div>
							{/if}
						</dl>
					{/if}

					{#if descriptionParagraphs.length > 0}
						<div class="section">
							<span class="section-heading small-caps">Description</span>
							<div class="description-pane">
								<div class="description-clamp" class:collapsed={collapsible && !expanded}>
									{#each visibleParagraphs as para}
										<p class="description-text">{para}</p>
									{/each}
								</div>
							</div>
							{#if collapsible}
								<button type="button" class="read-more small-caps" onclick={() => (expanded = !expanded)}>
									{expanded ? 'Show less' : 'Read more'}
								</button>
							{/if}
						</div>
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
		border-radius: var(--r-card);
		width: min(1120px, 100%);
		height: min(88vh, 900px);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	.modal:focus-visible {
		outline: none;
	}
	.modal-close {
		position: absolute;
		top: var(--sp-4);
		right: var(--sp-4);
		z-index: 20;
		width: 30px;
		height: 30px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 50%;
		background: color-mix(in srgb, var(--ink-surface) 88%, transparent);
		border: 1px solid var(--ink-hairline);
		backdrop-filter: blur(6px);
		-webkit-backdrop-filter: blur(6px);
		padding: 0;
		cursor: pointer;
		color: var(--bone);
		transition: color 0.15s, border-color 0.15s;
	}
	.modal-close:hover,
	.modal-close:focus-visible {
		color: var(--brass);
		border-color: var(--brass);
	}

	/* Header band */
	.header-band {
		position: relative;
		flex: 0 0 auto;
		width: 100%;
		box-sizing: border-box;
		padding: var(--sp-8) var(--sp-8) var(--sp-16);
		min-height: 168px;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		overflow: hidden;
		background: var(--ink-surface);
		border-bottom: var(--hairline);
		color: var(--bone);
		--band-accent: var(--brass-text);
	}
	/* Same rationale as .modal-close above: the backdrop is a heavily
	   darkened photo regardless of theme, so its text uses a fixed light
	   ink rather than tokens that would go dark-on-dark in the light theme. */
	.header-band.with-cover {
		color: #f3ead5;
		--band-accent: #c79a52;
	}
	.band-bg {
		position: absolute;
		inset: -20px;
		background-size: cover;
		background-position: center;
		filter: blur(28px) saturate(1.2);
		transform: scale(1.15);
	}
	.band-scrim {
		position: absolute;
		inset: 0;
		background: linear-gradient(180deg, rgba(0, 0, 0, 0.3) 0%, rgba(0, 0, 0, 0.55) 55%, rgba(0, 0, 0, 0.85) 100%);
	}
	.band-content {
		position: relative;
		z-index: 1;
		padding-right: var(--sp-8);
	}
	.band-title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-28);
		color: currentColor;
		margin: 0;
	}
	.band-author {
		font-family: var(--serif-body);
		color: currentColor;
		opacity: 0.78;
		margin: calc(-1 * var(--sp-1)) 0 0;
	}
	.band-series {
		color: var(--band-accent);
		margin: var(--sp-1) 0 0;
	}

	.modal-content-pad {
		flex: 1 1 auto;
		min-height: 0;
		padding: 0 var(--sp-8) var(--sp-8);
		display: flex;
	}
	.modal-body {
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		gap: var(--sp-8);
	}
	.cover-col {
		/* position: relative keeps this box in the same paint tier as the
		   positioned .header-band, so the negative-margin overlap below
		   paints on top of the band instead of being painted over by it. */
		position: relative;
		flex: 0 0 auto;
		width: 260px;
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		align-self: flex-start;
		margin-top: calc(-1 * var(--sp-12));
	}
	.cover {
		width: 100%;
		border-radius: var(--r-cover);
		display: block;
		box-shadow: 0 16px 30px -14px rgba(0, 0, 0, 0.6);
	}
	:root[data-theme='light'] .cover {
		box-shadow: 0 16px 30px -16px rgba(90, 72, 48, 0.45);
	}
	.action-stack {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.action-stack .btn-primary,
	.action-stack .btn-secondary {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--sp-2);
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
	.link-external {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 4px;
		color: var(--brass-text);
		text-decoration: none;
		text-align: center;
		padding: var(--sp-1) 0;
		transition: opacity 0.15s ease;
	}
	.link-external:hover,
	.link-external:focus-visible {
		opacity: 0.75;
	}

	.details-col {
		flex: 1;
		min-width: 0;
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
		padding-top: var(--sp-4);
	}

	.ratings-row {
		flex: 0 0 auto;
		display: flex;
		align-items: center;
		flex-wrap: wrap;
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
	.ratings-divider {
		width: 1px;
		align-self: stretch;
		background: var(--ink-hairline);
		margin: 0 var(--sp-2);
	}
	.avg-rating {
		font-family: var(--serif-display);
		color: var(--bone);
	}
	.rating-label {
		color: var(--bone-faint);
	}

	.chips {
		flex: 0 0 auto;
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}
	.chip {
		display: inline-block;
		padding: 2px 8px;
		border-radius: var(--r-chip);
		background: transparent;
		border: 1px solid var(--ink-hairline);
		color: var(--bone-muted);
		font-size: 10px;
	}

	.facts {
		flex: 0 0 auto;
		display: flex;
		flex-wrap: wrap;
		row-gap: var(--sp-4);
		column-gap: 0;
		margin: 0;
	}
	.fact {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 0 var(--sp-6);
		border-left: var(--hairline);
	}
	.fact:first-child {
		padding-left: 0;
		border-left: none;
	}
	.fact-label {
		color: var(--bone-faint);
	}
	.fact-value {
		margin: 0;
		color: var(--bone);
		font-family: var(--mono);
		font-size: var(--fs-16);
	}

	.section {
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		padding-top: var(--sp-4);
	}
	.section-heading {
		flex: 0 0 auto;
		color: var(--bone-muted);
	}
	.description-pane {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		padding-right: var(--sp-3);
		scrollbar-width: thin;
		scrollbar-color: var(--ink-hairline) transparent;
	}
	.description-pane::-webkit-scrollbar {
		width: 8px;
	}
	.description-pane::-webkit-scrollbar-track {
		background: transparent;
	}
	.description-pane::-webkit-scrollbar-thumb {
		background: var(--ink-hairline);
		border-radius: var(--r-chip);
	}
	.description-pane::-webkit-scrollbar-thumb:hover {
		background: var(--brass-dim);
	}
	.description-clamp {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		padding: var(--sp-3) 0;
	}
	.description-clamp.collapsed {
		padding-bottom: var(--sp-4);
	}
	.description-clamp.collapsed::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		height: 3.6em;
		background: linear-gradient(to bottom, transparent, var(--ink-surface));
		pointer-events: none;
	}
	.description-text {
		font-family: var(--serif-body);
		font-size: var(--fs-14);
		color: var(--bone);
		line-height: 1.65;
		margin: 0;
	}
	.read-more {
		flex: 0 0 auto;
		align-self: flex-start;
		background: none;
		border: none;
		padding: 0;
		margin-top: var(--sp-1);
		color: var(--brass-text);
		cursor: pointer;
		transition: opacity 0.15s ease;
	}
	.read-more:hover,
	.read-more:focus-visible {
		opacity: 0.75;
	}

	.btn-primary,
	.btn-secondary {
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
	.btn-secondary {
		background: none;
		border: 1px solid var(--brass-dim);
		color: var(--bone-muted);
		padding: var(--sp-1) var(--sp-4);
		font-size: 11px;
		transition: color 0.15s ease, border-color 0.15s ease;
	}
	.btn-secondary:hover,
	.btn-secondary:focus-visible {
		color: var(--brass-text);
		border-color: var(--brass);
	}

	@media (prefers-reduced-motion: reduce) {
		.modal-close,
		.link-external,
		.read-more,
		.btn-secondary {
			transition: none;
		}
	}

	@media (max-width: 700px) {
		.modal {
			height: auto;
			max-height: 88vh;
			overflow-y: auto;
			overflow-x: hidden;
		}
		.header-band {
			padding: var(--sp-6) var(--sp-6) var(--sp-8);
			min-height: 120px;
		}
		.band-content {
			padding-right: var(--sp-6);
		}
		.modal-content-pad {
			min-height: auto;
			padding: 0 var(--sp-6) var(--sp-6);
		}
		.modal-body {
			min-height: auto;
			flex-direction: column;
		}
		.details-col {
			min-height: auto;
		}
		.section {
			flex: 0 0 auto;
			min-height: auto;
		}
		.description-pane {
			flex: 0 0 auto;
			overflow-y: visible;
			padding-right: 0;
		}
		.cover-col {
			width: 100%;
			align-self: auto;
			align-items: center;
			margin-top: calc(-1 * var(--sp-8));
		}
		.cover {
			max-width: 200px;
		}
		.action-stack {
			width: 100%;
			max-width: 260px;
		}
		.link-external {
			width: 100%;
			max-width: 260px;
			margin: 0 auto;
		}
	}

	/* Short viewports (wide window, little vertical room): the two-column
	   layout above no longer scrolls as a whole, so the fixed-width cover
	   at its full size can outgrow the modal's fixed height and get clipped
	   by .modal's overflow: hidden. Shrink the band and cover so the left
	   column's natural height fits, leaving the description pane a few
	   visible lines. */
	@media (max-height: 760px) and (min-width: 701px) {
		.modal {
			height: 88vh;
		}
		.header-band {
			padding: var(--sp-6) var(--sp-6) var(--sp-8);
			min-height: 120px;
		}
		.cover-col {
			width: 180px;
			gap: var(--sp-2);
			margin-top: calc(-1 * var(--sp-8));
		}
		.action-stack {
			gap: var(--sp-1);
		}
		.modal-content-pad {
			padding-bottom: var(--sp-6);
		}
	}
</style>
