<script lang="ts">
	import type { GoodreadsStatsMonth, GoodreadsStatsCoverage } from '$lib/types';

	let { data, coverage }: { data: GoodreadsStatsMonth[]; coverage: GoodreadsStatsCoverage } =
		$props();

	const MONTH_ABBR = [
		'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
	];

	function monthLabel(key: string): string {
		const [y, m] = key.split('-');
		return `${MONTH_ABBR[Number(m) - 1]} '${y.slice(2)}`;
	}

	const W = 640;
	const H = 240;
	const ML = 34;
	const MR = 34;
	const MT = 12;
	const MB = 34;
	const innerW = W - ML - MR;
	const innerH = H - MT - MB;

	let n = $derived(data.length);
	let maxBooks = $derived(Math.max(1, ...data.map((d) => d.books)));
	let maxPages = $derived(Math.max(1, ...data.map((d) => d.pages)));
	let slot = $derived(n > 0 ? innerW / n : innerW);
	let barWidth = $derived(Math.max(2, slot * 0.5));

	let bars = $derived(
		data.map((d, i) => {
			const h = (d.books / maxBooks) * innerH;
			return {
				x: ML + i * slot + (slot - barWidth) / 2,
				y: MT + innerH - h,
				width: barWidth,
				height: h,
			};
		}),
	);

	let linePoints = $derived(
		data.map((d, i) => {
			const x = ML + i * slot + slot / 2;
			const y = MT + innerH - (d.pages / maxPages) * innerH;
			return { x, y };
		}),
	);

	let linePath = $derived(
		linePoints.length > 0
			? 'M ' + linePoints.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' L ')
			: '',
	);

	// Show only as many x-axis labels as fit without colliding.
	let labelStep = $derived(Math.max(1, Math.ceil(n / 8)));

	let booksTicks = $derived([0, Math.round(maxBooks / 2), maxBooks]);
	let pagesTicks = $derived([0, Math.round(maxPages / 2), maxPages]);
</script>

<figure class="chart-figure">
	{#if n === 0}
		<p class="empty-note">No dated finishes yet to chart.</p>
	{:else}
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-labelledby="monthly-chart-title"
		>
			<title id="monthly-chart-title">
				Books and pages read per month, {data[0].month} through {data[n - 1].month}
			</title>

			<!-- gridlines + left axis (books) -->
			{#each booksTicks as tick (tick)}
				{@const y = MT + innerH - (tick / maxBooks) * innerH}
				<line x1={ML} y1={y} x2={W - MR} y2={y} class="gridline" />
				<text x={ML - 6} y={y + 3} class="axis-label left">{tick}</text>
			{/each}

			<!-- right axis (pages) -->
			{#each pagesTicks as tick (tick)}
				{@const y = MT + innerH - (tick / maxPages) * innerH}
				<text x={W - MR + 6} y={y + 3} class="axis-label right">{tick}</text>
			{/each}

			<!-- bars: books per month -->
			{#each bars as bar, i (data[i].month)}
				<rect
					x={bar.x}
					y={bar.y}
					width={bar.width}
					height={bar.height}
					class="bar"
				/>
			{/each}

			<!-- line: pages per month -->
			{#if linePath}
				<path d={linePath} class="line" fill="none" />
				{#each linePoints as p, i (data[i].month)}
					<circle cx={p.x} cy={p.y} r="2.5" class="line-point" />
				{/each}
			{/if}

			<!-- x-axis month labels -->
			{#each data as d, i (d.month)}
				{#if i % labelStep === 0 || i === n - 1}
					<text
						x={ML + i * slot + slot / 2}
						y={H - MB + 16}
						class="axis-label month"
					>
						{monthLabel(d.month)}
					</text>
				{/if}
			{/each}
		</svg>

		<div class="legend small-caps">
			<span class="legend-item"><span class="swatch brass"></span>Books</span>
			<span class="legend-item"><span class="swatch sage"></span>Pages</span>
		</div>
	{/if}

	<p class="coverage-note">
		Covers {coverage.with_date_read} of {coverage.read_total} read books with a recorded finish
		date.
	</p>
</figure>

<style>
	.chart-figure {
		margin: 0;
	}
	svg {
		width: 100%;
		height: auto;
		display: block;
	}
	.gridline {
		stroke: var(--ink-hairline);
		stroke-width: 1;
	}
	.axis-label {
		font-family: var(--mono);
		font-size: 8px;
		fill: var(--bone-faint);
	}
	.axis-label.left {
		text-anchor: end;
	}
	.axis-label.right {
		text-anchor: start;
		fill: var(--sage);
	}
	.axis-label.month {
		text-anchor: middle;
	}
	.bar {
		fill: var(--brass);
	}
	.line {
		stroke: var(--sage);
		stroke-width: 1.5;
	}
	.line-point {
		fill: var(--sage);
	}
	.legend {
		display: flex;
		gap: var(--sp-4);
		margin-top: var(--sp-2);
		color: var(--bone-muted);
	}
	.legend-item {
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
	}
	.swatch {
		display: inline-block;
		width: 9px;
		height: 9px;
		border-radius: 1px;
	}
	.swatch.brass {
		background: var(--brass);
	}
	.swatch.sage {
		background: var(--sage);
	}
	.empty-note {
		font-style: italic;
		color: var(--bone-muted);
	}
	.coverage-note {
		font-size: var(--fs-12);
		color: var(--bone-faint);
		margin: var(--sp-2) 0 0;
	}
</style>
