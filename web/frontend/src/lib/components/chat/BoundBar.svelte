<script lang="ts">
	import type { CitationMark, SessionHeader } from '$lib/types';

	let {
		header,
		marks = [],
		litIds = new Set<string>(),
		thinking = false,
		onpick,
	}: {
		header: SessionHeader;
		marks?: CitationMark[];
		litIds?: Set<string>;
		thinking?: boolean;
		onpick?: (citationId: string) => void;
	} = $props();

	// Every volume in context is one segment. Prior volumes are whole by
	// definition, so they share the bar evenly and the current book gets twice
	// a share -- this is a picture of the sequence, not of page counts.
	const segments = $derived([
		...header.prior_books.map((b) => ({
			id: b.id,
			title: b.title,
			grow: 1,
			read: 1,
			current: false,
		})),
		{
			id: header.book_id,
			title: header.book_title,
			grow: 2,
			read:
				header.chapter_count > 0
					? Math.min(header.chapter_position / header.chapter_count, 1)
					: 0,
			current: true,
		},
	]);

	// A finished book has no meaningful "you are at" -- and its last addressable
	// chapter is often an appendix, which reads as nonsense in that sentence.
	const finished = $derived(
		header.chapter_count > 0 && header.chapter_position >= header.chapter_count,
	);

	function marksFor(bookId: string): CitationMark[] {
		return marks.filter((m) => m.book_id === bookId);
	}

	function pct(n: number): string {
		return `${(n * 100).toFixed(2)}%`;
	}
</script>

<div class="bound">
	<div class="labels">
		{#each segments as seg (seg.id)}
			<span class="small-caps seg-label" style="flex: {seg.grow};">{seg.title}</span>
		{/each}
	</div>

	<div class="track">
		{#each segments as seg (seg.id)}
			<span class="seg" class:current={seg.current} style="flex: {seg.grow};">
				<span class="fill" style="width: {pct(seg.read)};"></span>
				{#if seg.current && thinking}
					<span class="sweep" style="--read: {pct(seg.read)};"></span>
				{/if}
				{#each marksFor(seg.id) as mark (mark.id)}
					<button
						type="button"
						class="tick"
						class:lit={litIds.has(mark.id)}
						style="left: {pct(mark.fraction)};"
						title={mark.chapter_label}
						aria-label="Cited passage in {mark.chapter_label}"
						onclick={() => onpick?.(mark.id)}
					></button>
				{/each}
				{#if seg.current}
					<span class="mark" style="left: {pct(seg.read)};"></span>
					<span class="diamond" style="left: {pct(seg.read)};"></span>
				{/if}
			</span>
		{/each}
	</div>

	<div class="promise">
		<p>
			{#if finished}
				You have finished this book. Answers cover all of it, and nothing beyond.
			{:else}
				You are at <span class="small-caps here">{header.chapter_label}</span>. Answers will not
				reach beyond this point.
			{/if}
		</p>
		<span class="small-caps tokens">
			{header.token_estimate >= 1000
				? `${Math.round(header.token_estimate / 1000)}k`
				: header.token_estimate} tokens in context
		</span>
	</div>
</div>

<style>
	.labels {
		display: flex;
		gap: 7px;
		margin-bottom: 18px;
	}
	.seg-label {
		font-size: 9px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.track {
		display: flex;
		gap: 7px;
		align-items: center;
		height: 5px;
	}
	.seg {
		height: 5px;
		border-radius: 3px;
		position: relative;
		background: var(--ink-hairline);
	}
	.fill {
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		border-radius: 3px;
		background: var(--brass);
	}
	.seg:not(.current) .fill {
		opacity: 0.55;
	}
	.tick {
		position: absolute;
		bottom: 9px;
		width: 2px;
		height: 9px;
		padding: 0;
		border: none;
		border-radius: 1px;
		background: var(--brass-dim);
		opacity: 0.75;
		cursor: pointer;
		transition:
			background 0.18s ease,
			height 0.18s ease,
			opacity 0.18s ease;
	}
	.tick:hover,
	.tick.lit {
		background: var(--brass);
		height: 15px;
		opacity: 1;
	}
	.mark {
		position: absolute;
		top: -5px;
		bottom: -5px;
		width: 1px;
		background: var(--brass);
	}
	.diamond {
		position: absolute;
		top: -9px;
		width: 5px;
		height: 5px;
		margin-left: -2px;
		transform: rotate(45deg);
		background: var(--brass);
	}
	/* The model reads the whole readable set, so the sweep crosses exactly that span. */
	.sweep {
		position: absolute;
		top: -4px;
		bottom: -4px;
		width: 62px;
		border-radius: 4px;
		pointer-events: none;
		background: linear-gradient(
			90deg,
			transparent,
			color-mix(in srgb, var(--quote) 80%, transparent),
			transparent
		);
		animation: sweep 1.7s cubic-bezier(0.4, 0, 0.3, 1) infinite;
	}
	@keyframes sweep {
		0% {
			left: -14%;
			opacity: 0;
		}
		14% {
			opacity: 1;
		}
		82% {
			opacity: 1;
		}
		100% {
			left: var(--read);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.sweep {
			animation: none;
			left: 0;
			width: var(--read);
			opacity: 0.5;
		}
	}
	.promise {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-top: 13px;
		gap: 20px;
	}
	.promise p {
		margin: 0;
		font-style: italic;
		font-size: 13.5px;
		color: var(--bone-faint);
	}
	.here {
		color: var(--brass-text);
		font-style: normal;
		font-size: 11px;
		letter-spacing: 0.1em;
	}
	.tokens {
		flex-shrink: 0;
		font-size: 9.5px;
		letter-spacing: 0.16em;
		color: var(--bone-faint);
	}
</style>
