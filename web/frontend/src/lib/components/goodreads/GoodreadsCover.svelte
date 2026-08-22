<script lang="ts">
	import type { GoodreadsBook } from '$lib/types';

	let {
		book,
		onopen,
		showReadTag = false,
	}: { book: GoodreadsBook; onopen: () => void; showReadTag?: boolean } = $props();

	let failed = $state(false);
</script>

<button type="button" class="cover-btn" onclick={onopen} aria-label="{book.title} by {book.author}">
	<div class="cover-card">
		{#if book.cover_large && !failed}
			<img class="cover-img" src={book.cover_large} alt="" loading="lazy" onerror={() => (failed = true)} />
		{:else}
			<div class="cover-fallback">
				<div class="fallback-title">{book.title}</div>
				<div class="fallback-author small-caps">{book.author}</div>
			</div>
		{/if}
		{#if showReadTag}
			<span class="read-tag small-caps">Read</span>
		{/if}
	</div>
</button>

<style>
	.cover-btn {
		display: block;
		width: 100%;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		transition: filter 0.15s, transform 0.15s;
	}
	.cover-btn:hover,
	.cover-btn:focus-visible {
		filter: brightness(1.1);
		transform: translateY(-2px);
	}
	.cover-btn:focus-visible {
		outline: 2px solid var(--brass);
		outline-offset: 2px;
	}
	.cover-card {
		position: relative;
		width: 100%;
		aspect-ratio: 2 / 3;
		border-radius: var(--r-cover);
		background: var(--ink-surface);
		border: var(--hairline);
		overflow: hidden;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.cover-img {
		display: block;
		max-width: 100%;
		max-height: 100%;
		width: auto;
		height: auto;
		object-fit: contain;
	}
	.cover-fallback {
		width: 100%;
		height: 100%;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		padding: var(--sp-3);
		gap: var(--sp-2);
	}
	.fallback-title {
		font-family: var(--serif-display);
		font-style: italic;
		color: var(--bone);
		font-size: var(--fs-14);
		line-height: 1.3;
	}
	.fallback-author {
		color: var(--bone-muted);
	}
	.read-tag {
		position: absolute;
		top: var(--sp-2);
		right: var(--sp-2);
		padding: 2px 6px;
		border-radius: var(--r-chip);
		background: var(--sage);
		color: var(--ink-surface);
	}
</style>
