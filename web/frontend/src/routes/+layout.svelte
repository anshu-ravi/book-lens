<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/chrome/Header.svelte';
	import PageFrame from '$lib/components/chrome/PageFrame.svelte';

	let { children } = $props();
</script>

<Header />
<PageFrame>
	{@render children()}
</PageFrame>
