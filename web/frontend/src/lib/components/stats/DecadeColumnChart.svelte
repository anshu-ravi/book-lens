<script lang="ts">
	import type { GoodreadsStatsDecade } from '$lib/types';
	import ChartTooltip from './ChartTooltip.svelte';
	import { vBarPath } from './chartUtils';

	let { data }: { data: GoodreadsStatsDecade[] } = $props();

	const H = 220;
	const ML = 34;
	const MR = 12;
	const MT = 10;
	const MB = 26;

	let w = $state(0);
	let hovered = $state<number | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	let n = $derived(data.length);
	let innerW = $derived(Math.max(0, w - ML - MR));
	let innerH = H - MT - MB;
	let maxBooks = $derived(Math.max(1, ...data.map((d) => d.books)));
	let slot = $derived(n > 0 ? innerW / n : innerW);
	let barWidth = $derived(Math.min(24, Math.max(2, slot - 6)));
	let ticks = $derived([0, Math.round(maxBooks / 2), maxBooks]);

	let bars = $derived(
		data.map((d, i) => {
			const height = (d.books / maxBooks) * innerH;
			return {
				x: ML + i * slot + (slot - barWidth) / 2,
				y: MT + innerH - height,
				width: barWidth,
				height,
				hitX: ML + i * slot,
			};
		}),
	);

	function setHovered(i: number, evt?: PointerEvent) {
		hovered = i;
		if (evt) {
			const rect = (evt.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
			if (rect) pointer = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
		} else {
			const b = bars[i];
			if (b) pointer = { x: b.x + b.width / 2, y: b.y };
		}
	}

	function onKeydown(evt: KeyboardEvent) {
		if (n === 0) return;
		if (evt.key === 'ArrowRight') {
			evt.preventDefault();
			setHovered(Math.min(n - 1, (hovered ?? -1) + 1));
		} else if (evt.key === 'ArrowLeft') {
			evt.preventDefault();
			setHovered(Math.max(0, (hovered ?? n) - 1));
		} else if (evt.key === 'Escape') {
			hovered = null;
		}
	}

	function optionId(i: number): string {
		return `decade-opt-${i}`;
	}

	let plotLabel = $derived(
		n === 0
			? 'Books read by decade of original publication'
			: `Books read by decade of original publication, ${data[0].decade}s through ${data[n - 1].decade}s`,
	);
</script>

<div
	class="plot"
	bind:clientWidth={w}
	tabindex="0"
	role="listbox"
	aria-label={plotLabel}
	aria-activedescendant={hovered !== null ? optionId(hovered) : undefined}
	onkeydown={onKeydown}
>
	{#if w > 0}
		{#if n === 0}
			<p class="empty-note">No publication years recorded yet.</p>
		{:else}
			<svg width={w} height={H} viewBox="0 0 {w} {H}" role="presentation">
				{#each ticks as tick (tick)}
					{@const y = MT + innerH - (tick / maxBooks) * innerH}
					<line x1={ML} y1={y} x2={w - MR} y2={y} class="gridline" />
					<text x={ML - 6} y={y + 4} class="axis-label left">{tick}</text>
				{/each}

				{#each bars as bar, i (data[i].decade)}
					{@const isDimmed = hovered !== null && hovered !== i}
					<path d={vBarPath(bar.x, bar.y, bar.width, bar.height)} class="bar" opacity={isDimmed ? 0.45 : 1} />
					<text x={ML + i * slot + slot / 2} y={H - MB + 16} class="axis-label decade">
						{data[i].decade}s
					</text>
					<rect
						x={bar.hitX}
						y={MT}
						width={slot}
						height={innerH}
						class="hit"
						role="option"
						id={optionId(i)}
						aria-selected={hovered === i}
						aria-label="{data[i].decade}s: {data[i].books} books"
						onpointerenter={(e) => setHovered(i, e)}
						onpointermove={(e) => setHovered(i, e)}
						onpointerleave={() => (hovered = null)}
					/>
				{/each}
			</svg>

			{#if hovered !== null && data[hovered]}
				<ChartTooltip x={pointer.x} y={pointer.y} containerWidth={w}>
					<strong>{data[hovered].decade}s</strong><br />
					{data[hovered].books} book{data[hovered].books === 1 ? '' : 's'}
				</ChartTooltip>
			{/if}
		{/if}
	{/if}
</div>

<style>
	.plot {
		position: relative;
		width: 100%;
	}
	.plot:focus-visible {
		outline: 1px solid var(--brass);
		outline-offset: 2px;
	}
	svg {
		display: block;
	}
	.gridline {
		stroke: var(--ink-hairline);
		stroke-width: 1;
	}
	.axis-label {
		font-family: var(--mono);
		font-variant-numeric: tabular-nums;
		font-size: 11px;
		fill: var(--bone-faint);
	}
	.axis-label.left {
		text-anchor: end;
	}
	.axis-label.decade {
		text-anchor: middle;
	}
	.bar {
		fill: var(--brass);
		transition: opacity 0.1s ease;
	}
	.hit {
		fill: transparent;
		cursor: pointer;
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
		margin: 0;
	}
</style>
