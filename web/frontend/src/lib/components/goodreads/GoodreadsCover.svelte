<script lang="ts">
	import type { GoodreadsBook } from '$lib/types';

	let { book, onopen }: { book: GoodreadsBook; onopen: () => void } = $props();

	let failed = $state(false);
</script>

<button type="button" class="cover-btn" onclick={onopen} aria-label="{book.title} by {book.author}">
	{#if book.cover_large && !failed}
		<img class="cover-img" src={book.cover_large} alt="" loading="lazy" onerror={() => (failed = true)} />
	{:else}
		<div class="cover-fallback">
			<div class="fallback-title">{book.title}</div>
			<div class="fallback-author small-caps">{book.author}</div>
		</div>
	{/if}
</button>

<style>
	.cover-btn {
		display: block;
		width: 100%;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		border-radius: var(--r-cover);
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
	.cover-img {
		display: block;
		width: 100%;
		height: auto;
		border-radius: var(--r-cover);
	}
	.cover-fallback {
		width: 100%;
		aspect-ratio: 2 / 3;
		border-radius: var(--r-cover);
		background: var(--ink-surface);
		border: var(--hairline);
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
</style>
