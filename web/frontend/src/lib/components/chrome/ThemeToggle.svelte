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
	class="theme-toggle small-caps"
	onclick={toggle}
	aria-label={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
>
	{theme === 'light' ? 'Light' : 'Dark'}
</button>

<style>
	.theme-toggle {
		background: none;
		border: var(--hairline);
		color: var(--bone-muted);
		padding: var(--sp-1) var(--sp-3);
		border-radius: var(--r-chip);
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}
	.theme-toggle:hover {
		color: var(--brass);
		border-color: var(--brass);
	}
</style>
