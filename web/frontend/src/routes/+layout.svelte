<script lang="ts">
	import '../app.css';
	import Rail from '$lib/components/chrome/Rail.svelte';

	let { children } = $props();
</script>

<div class="frame">
	<div class="app">
		<Rail />
		<main class="main">
			{@render children()}
		</main>
	</div>
</div>

<style>
	/* No overflow:hidden here -- that would make .app the containing block for
	   the rail's `position: sticky` and the rail would scroll away with the page. */
	.frame {
		padding: var(--sp-6);
		min-height: 100vh;
	}
	.app {
		display: grid;
		grid-template-columns: 250px minmax(0, 1fr);
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-box);
		min-height: calc(100vh - var(--sp-12));
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2), 0 28px 64px -28px rgba(0, 0, 0, 0.62);
	}
	:root[data-theme='light'] .app {
		box-shadow: 0 1px 2px rgba(90, 72, 48, 0.1), 0 28px 64px -30px rgba(90, 72, 48, 0.4);
	}
	.main {
		padding: var(--sp-8) var(--sp-8) var(--sp-12);
		min-width: 0;
	}
	@media (max-width: 900px) {
		.frame {
			padding: var(--sp-4);
		}
		.app {
			grid-template-columns: 1fr;
		}
		.main {
			padding: var(--sp-6);
		}
	}
</style>
