<script lang="ts">
	import type { GoodreadsStatsMonth } from '$lib/types';
	import ChartTooltip from './ChartTooltip.svelte';
	import { vBarPath, monthIndex, monthFullLabel } from './chartUtils';

	let { data, measure }: { data: GoodreadsStatsMonth[]; measure: 'books' | 'pages' } = $props();

	const TITLE_CAP = 6;

	const H = 260;
	const ML = 46;
	const MR = 16;
	const MT = 16;
	const MB = 30;

	let w = $state(0);
	let hovered = $state<number | null>(null);
	let pointer = $state({ x: 0, y: 0 });

	function valueOf(d: GoodreadsStatsMonth): number {
		return measure === 'books' ? d.count : d.pages;
	}

	let n = $derived(data.length);
	let innerW = $derived(Math.max(0, w - ML - MR));
	let innerH = H - MT - MB;
	let maxVal = $derived(Math.max(1, ...data.map(valueOf)));
	let slot = $derived(n > 0 ? innerW / n : innerW);
	let barWidth = $derived(Math.min(24, Math.max(2, slot - 4)));

	let bars = $derived(
		data.map((d, i) => {
			const val = valueOf(d);
			const height = (val / maxVal) * innerH;
			return {
				x: ML + i * slot + (slot - barWidth) / 2,
				y: MT + innerH - height,
				width: barWidth,
				height,
				hitX: ML + i * slot,
				val,
			};
		}),
	);

	let ticks = $derived([0, Math.round(maxVal / 2), maxVal]);

	// Year labels drawn once at January of each year present (or the first
	// month in the filtered range, if it doesn't start in January).
	let yearLabels = $derived(
		data
			.map((d, i) => ({ i, key: d.month }))
			.filter(({ i, key }) => i === 0 || monthIndex(key) === 0)
			.map(({ i, key }) => ({ x: ML + i * slot + slot / 2, year: monthYearOf(key) })),
	);

	function monthYearOf(key: string): string {
		return key.split('-')[0];
	}

	function setHovered(i: number, evt?: PointerEvent) {
		hovered = i;
		if (evt) {
			const rect = (evt.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
			if (rect) {
				pointer = { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
			}
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
		return `timeline-opt-${i}`;
	}

	let plotLabel = $derived(
		n === 0
			? `${measure === 'books' ? 'Books' : 'Pages'} read per month`
			: `${measure === 'books' ? 'Books' : 'Pages'} read per month, ${data[0].month} through ${data[n - 1].month}`,
	);

	let hoveredTitles = $derived.by(() => {
		if (hovered === null || !data[hovered]) return { shown: [] as string[], more: 0 };
		const titles = data[hovered].books.map((b) => b.title);
		return { shown: titles.slice(0, TITLE_CAP), more: Math.max(0, titles.length - TITLE_CAP) };
	});
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
			<p class="empty-note">No dated finishes in this range.</p>
		{:else}
			<svg width={w} height={H} viewBox="0 0 {w} {H}" role="presentation">
				{#each ticks as tick (tick)}
					{@const y = MT + innerH - (tick / maxVal) * innerH}
					<line x1={ML} y1={y} x2={w - MR} y2={y} class="gridline" />
					<text x={ML - 8} y={y + 4} class="axis-label left">{tick.toLocaleString()}</text>
				{/each}

				{#each yearLabels as yl (yl.x)}
					<text x={yl.x} y={H - MB + 18} class="axis-label year">{yl.year}</text>
				{/each}

				{#each bars as bar, i (data[i].month)}
					{@const isHovered = hovered === i}
					{@const isDimmed = hovered !== null && !isHovered}
					<path
						d={vBarPath(bar.x, bar.y, bar.width, bar.height)}
						class="bar"
						opacity={isDimmed ? 0.45 : 1}
					/>
					<rect
						x={bar.hitX}
						y={MT}
						width={slot}
						height={innerH}
						class="hit"
						role="option"
						id={optionId(i)}
						aria-selected={hovered === i}
						aria-label="{monthFullLabel(data[i].month)}: {data[i].count} book{data[i].count === 1
							? ''
							: 's'}, {data[i].pages.toLocaleString()} pages"
						onpointerenter={(e) => setHovered(i, e)}
						onpointermove={(e) => setHovered(i, e)}
						onpointerleave={() => (hovered = null)}
					/>
				{/each}
			</svg>

			{#if hovered !== null && data[hovered]}
				<ChartTooltip x={pointer.x} y={pointer.y} containerWidth={w}>
					<div class="month-tooltip">
						<strong>{monthFullLabel(data[hovered].month)}</strong><br />
						{measure === 'books'
							? `${data[hovered].count} book${data[hovered].count === 1 ? '' : 's'}`
							: `${data[hovered].pages.toLocaleString()} pages`}
						{#if hoveredTitles.shown.length > 0}
							<br />
							{#each hoveredTitles.shown as title (title)}
								{title}<br />
							{/each}
							{#if hoveredTitles.more > 0}
								+{hoveredTitles.more} more
							{/if}
						{/if}
					</div>
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
	.axis-label.year {
		text-anchor: middle;
		font-family: var(--sans-caps);
		letter-spacing: var(--tracking-caps);
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
	.month-tooltip {
		white-space: normal;
		max-width: 220px;
	}
</style>
