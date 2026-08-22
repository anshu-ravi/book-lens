<script lang="ts">
	import type { UnifiedEntry } from '$lib/types';

	let {
		entry,
		percent,
		chaptersRead,
		onopen,
		onedit,
		onask,
	}: {
		entry: UnifiedEntry;
		/** Joined from GET /api/library by book_id -- the unified entry itself carries no chapter_count. */
		percent: number | null;
		chaptersRead: number | null;
		onopen: () => void;
		onedit: () => void;
		onask: () => void;
	} = $props();

	let coverFailed = $state(false);
</script>

<article class="rc">
	<button type="button" class="rc-c" onclick={onopen} aria-label="View {entry.display_title}">
		{#if entry.cover && !coverFailed}
			<img src={entry.cover} alt="" loading="lazy" onerror={() => (coverFailed = true)} />
		{:else}
			<div class="fb"></div>
		{/if}
	</button>
	<div class="rc-b">
		{#if entry.series}
			<span class="small-caps rc-ser">{entry.series}</span>
		{/if}
		<h3>
			<button type="button" class="rc-title-btn" onclick={onopen}>{entry.display_title}</button>
		</h3>
		{#if entry.author}
			<span class="rc-by">{entry.author}</span>
		{/if}
		{#if entry.askable && percent !== null}
			<div class="rc-p">
				<div class="rc-bar"><span style="width:{percent}%"></span></div>
				<div class="rc-meta">
					<span>Chapter {chaptersRead}</span>
					<span>{percent}%</span>
				</div>
			</div>
			<div class="rc-acts">
				<button class="rc-btn small-caps" onclick={onedit}>Update position</button>
				<button class="rc-ico" title="Ask about this book" aria-label="Ask about this book" onclick={onask}>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
						<path
							d="M21 12a8 8 0 0 1-8 8H7l-4 3v-4.6A8 8 0 0 1 11 4h2a8 8 0 0 1 8 8Z"
						/>
					</svg>
				</button>
			</div>
		{:else}
			<p class="rc-no-epub">No EPUB yet — upload one to track your position and ask questions about it.</p>
			<a class="rc-btn small-caps rc-upload" href="/upload">Upload EPUB</a>
		{/if}
	</div>
</article>

<style>
	.rc {
		display: flex;
		gap: var(--sp-6);
		background: var(--ink-bg);
		border: var(--hairline);
		border-radius: var(--r-card);
		padding: var(--sp-6);
		flex: 1 1 420px;
		max-width: 540px;
		box-shadow: 0 12px 26px -18px rgba(0, 0, 0, 0.6);
	}
	:root[data-theme='light'] .rc {
		box-shadow: 0 12px 26px -20px rgba(90, 72, 48, 0.5);
	}
	.rc-c {
		flex: 0 0 124px;
		height: 186px;
		border-radius: 1px var(--r-cover) var(--r-cover) 1px;
		overflow: hidden;
		background: var(--ink-surface);
		box-shadow: 0 12px 22px -8px rgba(0, 0, 0, 0.6), inset 2px 0 0 rgba(0, 0, 0, 0.22);
		padding: 0;
		border: none;
		cursor: pointer;
	}
	:root[data-theme='light'] .rc-c {
		box-shadow: 0 12px 22px -8px rgba(90, 72, 48, 0.42), inset 2px 0 0 rgba(90, 72, 48, 0.16);
	}
	.rc-c img,
	.rc-c .fb {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.fb {
		background: var(--ink-surface);
	}
	.rc-b {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		min-width: 0;
		flex: 1;
	}
	.rc-ser {
		color: var(--brass-text);
	}
	.rc-b h3 {
		margin: 2px 0 0;
		line-height: 1.15;
	}
	.rc-title-btn {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		text-align: left;
		font-family: var(--serif-display);
		font-style: italic;
		font-weight: 400;
		font-size: var(--fs-22);
		color: var(--bone);
	}
	.rc-title-btn:hover {
		text-decoration: underline;
	}
	.rc-by {
		font-size: var(--fs-13);
		color: var(--bone-muted);
	}
	.rc-p {
		margin-top: auto;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.rc-bar {
		height: 2px;
		background: var(--ink-hairline);
		overflow: hidden;
	}
	.rc-bar span {
		display: block;
		height: 100%;
		background: var(--brass);
	}
	.rc-meta {
		display: flex;
		justify-content: space-between;
		font-family: var(--mono);
		font-size: var(--fs-12);
		color: var(--bone-faint);
	}
	:root[data-theme='light'] .rc-meta {
		color: var(--bone-muted);
	}
	.rc-acts {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		margin-top: var(--sp-4);
	}
	.rc-btn {
		border: 1px solid var(--brass);
		color: var(--brass-text);
		border-radius: var(--r-chip);
		padding: 6px var(--sp-3);
		background: none;
		cursor: pointer;
		text-decoration: none;
		display: inline-block;
	}
	.rc-btn:hover {
		background: var(--brass);
		color: var(--ink-bg);
	}
	.rc-ico {
		color: var(--bone-faint);
		display: flex;
		padding: 4px;
		background: none;
		border: none;
		cursor: pointer;
	}
	.rc-ico svg {
		width: 17px;
		height: 17px;
	}
	.rc-ico:hover {
		color: var(--brass);
	}
	.rc-no-epub {
		margin: auto 0 0;
		font-size: var(--fs-13);
		font-style: italic;
		color: var(--bone-muted);
	}
	.rc-upload {
		margin-top: var(--sp-3);
		align-self: flex-start;
	}
	@media (max-width: 900px) {
		.rc {
			flex: 1 1 100%;
		}
		.rc-c {
			flex: 0 0 96px;
			height: 144px;
		}
	}
</style>
