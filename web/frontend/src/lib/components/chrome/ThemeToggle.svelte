<script lang="ts">
	type Theme = 'light' | 'dark';

	function currentTheme(): Theme {
		if (typeof document === 'undefined') return 'dark';
		return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
	}

	let theme = $state<Theme>(currentTheme());

	function toggle() {
		theme = theme === 'light' ? 'dark' : 'light';
		document.documentElement.setAttribute('data-theme', theme);
		localStorage.setItem('booklens-theme', theme);
	}
</script>

<button
	type="button"
	class="theme-toggle"
	onclick={toggle}
	aria-label={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
>
	{#if theme === 'light'}
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
			<circle cx="12" cy="12" r="4.2" />
			<path
				d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"
			/>
		</svg>
	{:else}
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
			<path d="M20 13.5A8 8 0 0 1 10.5 4a8.2 8.2 0 1 0 9.5 9.5Z" />
		</svg>
	{/if}
</button>

<style>
	.theme-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		flex-shrink: 0;
		color: var(--bone-muted);
		border: var(--hairline);
		border-radius: var(--r-chip);
		background: none;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}
	.theme-toggle:hover {
		color: var(--brass-text);
		border-color: var(--brass);
	}
	.theme-toggle svg {
		width: 16px;
		height: 16px;
	}
</style>
