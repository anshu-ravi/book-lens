<script lang="ts">
	import type { UnifiedEntry } from '$lib/types';

	let {
		entry,
		inSeriesRun,
		onopen,
	}: { entry: UnifiedEntry; inSeriesRun: boolean; onopen: () => void } = $props();

	let failed = $state(false);

	// A series line is redundant only when it's the book's own title standing in
	// for an unnamed series AND that book is alone in its group (no siblings).
	const showSeries = $derived(
		entry.series !== null &&
			(inSeriesRun ||
				entry.series.toLowerCase().trim() !== entry.display_title.toLowerCase().trim()),
	);

	// The unified entry carries chapter_idx/ceiling_seq but no chapter_count, so
	// there is no real percentage to compute -- a "reading" pill stands in for a
	// progress bar rather than a fabricated number.
	const isReading = $derived(entry.progress !== null && entry.progress.status === 'reading');

	const stars = $derived(
		entry.user_rating ? Array.from({ length: 5 }, (_, i) => i < entry.user_rating!) : null,
	);
</script>

<button type="button" class="card" onclick={onopen} aria-label="{entry.display_title} by {entry.author}">
	<div class="cover-card">
		{#if entry.cover && !failed}
			<img class="cover-img" src={entry.cover} alt="" loading="lazy" onerror={() => (failed = true)} />
		{:else}
			<div class="cover-fallback">
				<span class="fallback-rule"></span>
				<div class="fallback-title">{entry.display_title}</div>
				<div class="fallback-author small-caps">{entry.author}</div>
			</div>
		{/if}
		{#if isReading}
			<span class="reading-pill small-caps">Reading</span>
		{/if}
	</div>
	<div class="meta">
		<p class="title">{entry.display_title}</p>
		<span class="author small-caps">{entry.author}</span>
		{#if stars}
			<span class="stars" aria-hidden="true">
				{#each stars as filled}
					<span class="star" class:filled>★</span>
				{/each}
			</span>
		{/if}
		{#if showSeries}
			<span class="series small-caps">
				{entry.series}{entry.series_number !== null ? ` · Book ${entry.series_number}` : ''}
			</span>
		{/if}
		{#if entry.askable}
			<span class="ask small-caps" title="EPUB ingested — you can ask about this book">EPUB</span>
		{/if}
	</div>
</button>

<style>
	.card {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		background: var(--ink-bg);
		border: var(--hairline);
		border-radius: var(--r-card);
		padding: var(--sp-3);
		cursor: pointer;
		text-align: left;
		transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0);
	}
	.card:hover {
		transform: translateY(-3px);
		border-color: var(--brass);
		box-shadow: 0 16px 28px -16px rgba(0, 0, 0, 0.55);
	}
	:root[data-theme='light'] .card:hover {
		box-shadow: 0 16px 28px -18px rgba(90, 72, 48, 0.45);
	}
	.card:focus-visible {
		outline: 2px solid var(--brass);
		outline-offset: 2px;
	}
	@media (prefers-reduced-motion: reduce) {
		.card {
			transition: border-color 0.18s ease, box-shadow 0.18s ease;
		}
		.card:hover {
			transform: none;
		}
	}

	.cover-card {
		position: relative;
		width: 100%;
		flex: 0 0 auto;
		aspect-ratio: 2 / 3;
		border-radius: var(--r-cover);
		background: var(--ink-surface);
		overflow: hidden;
		box-shadow: 0 10px 18px -10px rgba(0, 0, 0, 0.55), inset 2px 0 0 rgba(0, 0, 0, 0.18);
		margin-bottom: var(--sp-3);
	}
	:root[data-theme='light'] .cover-card {
		box-shadow: 0 10px 18px -12px rgba(90, 72, 48, 0.4), inset 2px 0 0 rgba(90, 72, 48, 0.16);
	}
	.cover-img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
		transition: transform 0.18s ease;
	}
	.card:hover .cover-img {
		transform: scale(1.03);
	}
	@media (prefers-reduced-motion: reduce) {
		.cover-img {
			transition: none;
		}
		.card:hover .cover-img {
			transform: none;
		}
	}

	.cover-fallback {
		width: 100%;
		height: 100%;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		padding: var(--sp-4);
		gap: var(--sp-2);
		background: linear-gradient(180deg, var(--ink-surface) 0%, var(--ink-bg) 100%);
	}
	.fallback-rule {
		width: 28px;
		height: 1px;
		background: var(--brass);
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

	.reading-pill {
		position: absolute;
		top: 6px;
		left: 6px;
		padding: 2px 6px;
		border-radius: var(--r-chip);
		background: var(--brass);
		color: var(--ink-bg);
		font-size: 10px;
		letter-spacing: 0.14em;
	}
	:root[data-theme='light'] .reading-pill {
		color: var(--bone);
	}

	.ask {
		align-self: flex-start;
		margin-top: 2px;
		padding: 2px 6px;
		border-radius: var(--r-chip);
		border: 1px solid var(--brass-dim);
		background: transparent;
		color: var(--brass-text);
		font-size: 10px;
		letter-spacing: 0.12em;
	}

	.meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-height: 6em;
	}
	.title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-14);
		color: var(--bone);
		margin: 0;
		line-height: 1.3;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.author {
		color: var(--bone-muted);
	}
	.stars {
		letter-spacing: 1px;
		font-size: 10px;
	}
	.star {
		color: var(--brass-dim);
	}
	.star.filled {
		color: var(--brass);
	}
	.series {
		color: var(--brass-text);
	}
</style>
