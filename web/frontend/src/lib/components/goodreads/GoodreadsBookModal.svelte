<script lang="ts">
	import type { GoodreadsBook } from '$lib/types';
	import { shelfLabel } from '$lib/utils/goodreads-shelf';
	import { formatDateLong } from '$lib/utils/format-date';
	import { htmlToParagraphs } from '$lib/utils/strip-html';

	let { book, onclose }: { book: GoodreadsBook; onclose: () => void } = $props();

	const descriptionParagraphs = $derived(book.description ? htmlToParagraphs(book.description) : []);
	const stars = $derived(book.user_rating ? Array.from({ length: 5 }, (_, i) => i < book.user_rating!) : null);

	let coverFailed = $state(false);

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay">
	<button type="button" class="overlay-dismiss" aria-label="Close" onclick={onclose}></button>
	<div class="modal" role="dialog" aria-modal="true" aria-label={book.title}>
		<button type="button" class="modal-close" aria-label="Close" onclick={onclose}>
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M3 3l10 10M13 3 3 13" />
			</svg>
		</button>
		<div class="modal-body">
			<div class="cover-col">
				{#if book.cover_large && !coverFailed}
					<img
						class="cover"
						src={book.cover_large}
						alt=""
						onerror={() => (coverFailed = true)}
					/>
				{:else}
					<div class="cover cover-fallback">
						<div class="fallback-title">{book.title}</div>
						<div class="fallback-author small-caps">{book.author}</div>
					</div>
				{/if}
			</div>

			<div class="details-col">
				<h2 class="title">{book.title}</h2>
				<p class="author">by {book.author}</p>

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
					{#if book.average_rating !== null}
						<div class="rating-row">
							<span class="avg-rating">{book.average_rating.toFixed(2)}</span>
							<span class="rating-label small-caps">goodreads average</span>
						</div>
					{/if}
				</div>

				<div class="chips">
					<span class="chip shelf-chip small-caps">{shelfLabel(book.shelf)}</span>
					{#each book.custom_shelves as custom (custom)}
						<span class="chip custom-chip small-caps">{custom}</span>
					{/each}
				</div>

				<dl class="facts">
					{#if book.num_pages !== null}
						<div class="fact"><dt class="small-caps">Pages</dt><dd>{book.num_pages}</dd></div>
					{/if}
					{#if book.published_year !== null}
						<div class="fact"><dt class="small-caps">Published</dt><dd>{book.published_year}</dd></div>
					{/if}
					{#if book.isbn}
						<div class="fact"><dt class="small-caps">ISBN</dt><dd>{book.isbn}</dd></div>
					{/if}
					{#if book.date_added}
						<div class="fact"><dt class="small-caps">Added</dt><dd>{formatDateLong(book.date_added)}</dd></div>
					{/if}
					{#if book.date_started}
						<div class="fact"><dt class="small-caps">Started</dt><dd>{formatDateLong(book.date_started)}</dd></div>
					{/if}
					{#if book.date_read}
						<div class="fact"><dt class="small-caps">Finished</dt><dd>{formatDateLong(book.date_read)}</dd></div>
					{/if}
				</dl>

				{#if book.user_review}
					<div class="section">
						<span class="section-heading small-caps">Your review</span>
						<p class="review-text">{book.user_review}</p>
					</div>
				{/if}

				{#if descriptionParagraphs.length > 0}
					<div class="section">
						<span class="section-heading small-caps">Description</span>
						{#each descriptionParagraphs as para}
							<p class="description-text">{para}</p>
						{/each}
					</div>
				{/if}

				{#if book.goodreads_url}
					<a class="goodreads-link small-caps" href={book.goodreads_url} target="_blank" rel="noopener noreferrer">
						View on Goodreads →
					</a>
				{/if}
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
	}
	.shelf-chip {
		background: color-mix(in srgb, var(--brass) 15%, transparent);
		color: var(--brass);
	}
	.custom-chip {
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
	.review-text,
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
	@media (max-width: 700px) {
		.modal-body {
			flex-direction: column;
		}
		.cover-col {
			width: 160px;
		}
	}
</style>
