<script lang="ts">
	let { children } = $props();
</script>

<div class="page-frame">
	<div class="page-inner">
		{@render children()}
	</div>
</div>

<style>
	.page-frame {
		padding: var(--frame-inset);
		min-height: calc(100vh - var(--header-h));
	}
	.page-inner {
		border: var(--hairline);
		min-height: calc(100vh - var(--header-h) - calc(var(--frame-inset) * 2));
		padding: var(--sp-8);
	}
	@media (max-width: 900px) {
		.page-frame {
			padding: var(--sp-4);
		}
		.page-inner {
			padding: var(--sp-4);
		}
	}
</style>
