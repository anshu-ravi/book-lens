<script lang="ts">
	import { page } from '$app/stores';
	import ThemeToggle from './ThemeToggle.svelte';

	const links = [
		{ href: '/', label: 'Library' },
		{ href: '/upload', label: 'Upload' },
		{ href: '/chat', label: 'Chat' },
	];
</script>

<header>
	<div class="header-inner">
		<div class="wordmark">
			<a href="/" class="brand">BookLens</a>
			<span class="tagline">· a reader's index</span>
		</div>

		<nav class="nav">
			{#each links as link (link.href)}
				<a
					href={link.href}
					class="nav-link small-caps"
					class:active={$page.url.pathname === link.href}
				>
					{link.label}
				</a>
			{/each}
		</nav>

		<div class="header-end">
			<ThemeToggle />
		</div>
	</div>
</header>

<style>
	header {
		height: var(--header-h);
		border-bottom: var(--hairline);
		background: var(--ink-bg);
		position: sticky;
		top: 0;
		z-index: 10;
	}
	.header-inner {
		height: 100%;
		padding: 0 var(--frame-inset);
		display: grid;
		grid-template-columns: 1fr auto 1fr;
		align-items: center;
		gap: var(--sp-8);
	}
	.wordmark {
		display: flex;
		align-items: baseline;
		gap: var(--sp-2);
		flex-shrink: 0;
		min-width: 0;
	}
	.brand {
		font-family: var(--serif-display);
		font-size: 1.375rem;
		color: var(--bone);
		text-decoration: none;
	}
	.tagline {
		font-family: var(--serif-body);
		font-size: var(--fs-14);
		font-style: italic;
		color: var(--bone-muted);
	}
	.nav {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--sp-8);
	}
	.header-end {
		display: flex;
		align-items: center;
		justify-content: flex-end;
	}
	@media (max-width: 700px) {
		.tagline {
			display: none;
		}
	}
	.nav-link {
		color: var(--bone-muted);
		text-decoration: none;
		padding-bottom: 4px;
		border-bottom: 1px solid transparent;
		transition: color 0.15s, border-color 0.15s;
	}
	.nav-link:hover {
		color: var(--bone);
	}
	.nav-link.active {
		color: var(--brass);
		border-bottom-color: var(--brass);
	}
</style>
