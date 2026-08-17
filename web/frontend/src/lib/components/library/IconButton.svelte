<script lang="ts">
	let {
		icon,
		label,
		onclick,
		tone = 'default',
	}: {
		icon: 'bookmark' | 'chat' | 'pencil' | 'close';
		label: string;
		onclick: () => void;
		tone?: 'default' | 'brass';
	} = $props();
</script>

<span class="icon-btn-wrap">
	<button type="button" class="icon-btn" class:brass={tone === 'brass'} aria-label={label} onclick={onclick}>
		{#if icon === 'bookmark'}
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M4 2.5h8a.5.5 0 0 1 .5.5v10.5l-4.5-3-4.5 3V3a.5.5 0 0 1 .5-.5Z" />
			</svg>
		{:else if icon === 'chat'}
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M2 3.5h12a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-.5.5H6l-2.8 2.4a.3.3 0 0 1-.5-.23V10.5H2a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5Z" />
			</svg>
		{:else if icon === 'pencil'}
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M10.5 2.5 13.5 5.5 5 14H2v-3z" />
				<path d="M9 4 12 7" />
			</svg>
		{:else if icon === 'close'}
			<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">
				<path d="M3 3l10 10M13 3 3 13" />
			</svg>
		{/if}
	</button>
	<span class="tip">{label}</span>
</span>

<style>
	.icon-btn-wrap {
		position: relative;
		display: inline-flex;
	}
	.icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		padding: var(--sp-1);
		cursor: pointer;
		color: var(--bone-muted);
		transition: color 0.15s;
	}
	.icon-btn:hover,
	.icon-btn:focus-visible {
		color: var(--brass);
	}
	.icon-btn.brass {
		color: var(--brass);
	}
	/* Above the button, never below: the icon row sits at the card's bottom edge
	   and the carousel track clips anything past it. */
	.tip {
		position: absolute;
		bottom: calc(100% + var(--sp-2));
		left: 50%;
		transform: translateX(-50%);
		background: var(--ink-surface);
		border: var(--hairline);
		padding: var(--sp-1) var(--sp-2);
		white-space: nowrap;
		pointer-events: none;
		opacity: 0;
		transition: opacity 0.12s;
		z-index: 20;
		color: var(--bone);
	}
	.icon-btn:hover + .tip,
	.icon-btn:focus-visible + .tip {
		opacity: 1;
	}
</style>
