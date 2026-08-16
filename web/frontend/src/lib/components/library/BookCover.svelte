<script lang="ts">
	import { seriesColor } from '$lib/utils/series-color';

	let {
		title,
		author,
		seriesId,
		positionInSeries,
		size = 'medium',
		coverUrl = null,
	}: {
		title: string;
		author?: string;
		seriesId: string;
		positionInSeries?: number;
		size?: 'thumb' | 'small' | 'medium' | 'large';
		coverUrl?: string | null;
	} = $props();

	const bg = $derived(seriesColor(seriesId));
	const authorSurname = $derived(author ? (author.split(' ').pop() ?? author) : '');

	const dims = {
		thumb: { w: 34, h: 51 },
		small: { w: 100, h: 150 },
		medium: { w: 160, h: 240 },
		large: { w: 280, h: 400 },
	};
	const { w, h } = $derived(dims[size]);

	// The parent only ever passes a URL when has_cover is true, but a real
	// cover can still fail to load at runtime -- fall back rather than break.
	let coverFailed = $state(false);
	$effect(() => {
		coverUrl;
		coverFailed = false;
	});
</script>

{#if coverUrl && !coverFailed}
	<div class="cover" style="width:{w}px;height:{h}px;">
		<img src={coverUrl} alt="" loading="lazy" onerror={() => (coverFailed = true)} />
	</div>
{:else}
	<div class="cover" style="width:{w}px;height:{h}px;background:{bg};">
		<div class="cover-top small-caps">{authorSurname}</div>
		<div class="cover-title">{title}</div>
		<div class="cover-bottom small-caps">
			{#if positionInSeries}<span class="vol">{positionInSeries}</span>{/if}
			<span class="brand-mark">Booklens</span>
		</div>
	</div>
{/if}

<style>
	.cover img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		border-radius: var(--r-cover);
	}
	.cover {
		border-radius: var(--r-cover);
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		overflow: hidden;
		flex-shrink: 0;
		container-type: inline-size;
	}
	.cover-top {
		position: absolute;
		top: 10px;
		left: 10px;
		right: 10px;
		font-size: var(--fs-12);
		color: var(--bone-muted);
	}
	.cover-title {
		font-family: var(--serif-display);
		font-style: italic;
		color: var(--bone);
		font-size: clamp(0.75rem, 12cqw, 1.125rem);
		text-align: center;
		padding: 8px;
		line-height: 1.3;
		z-index: 1;
	}
	.cover-bottom {
		position: absolute;
		bottom: 10px;
		left: 10px;
		right: 10px;
		display: flex;
		justify-content: space-between;
		font-size: 9px;
		color: var(--bone-faint);
	}
	.vol {
		color: var(--brass);
	}
</style>
