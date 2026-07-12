<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import type { AppConfig } from '$lib/types';
	import { initSupabase, getSupabase } from '$lib/supabase';
	import auth from '$lib/stores/auth.svelte';
	import { refreshLibrary } from '$lib/stores/library.svelte';
	import Header from '$lib/components/chrome/Header.svelte';
	import PageFrame from '$lib/components/chrome/PageFrame.svelte';

	let features = $state({ enable_extraction: true, enable_graph: true });

	onMount(async () => {
		try {
			const res = await fetch('/api/config');
			const config: AppConfig = await res.json();
			features.enable_extraction = config.enable_extraction ?? true;
			features.enable_graph = config.enable_graph ?? true;

			const supabase = initSupabase(config.supabase_url, config.supabase_anon_key);

			supabase.auth.onAuthStateChange((_event, session) => {
				auth.session = session;
				auth.user = session?.user ?? null;
			});

			const { data } = await supabase.auth.getSession();
			auth.session = data.session;
			auth.user = data.session?.user ?? null;
			auth.ready = true;

			if (auth.user) {
				await refreshLibrary();
			}
		} catch (e) {
			console.error('Bootstrap failed', e);
			auth.ready = true;
		}
	});

	$effect(() => {
		if (!auth.ready) return;
		const isLogin = $page.url.pathname === '/login';
		if (!auth.user && !isLogin) goto('/login');
	});

	let { children } = $props();
</script>

{#if !auth.ready}
	<div class="loading-screen">
		<span class="loading-text">Opening the index…</span>
	</div>
{:else if auth.user}
	<Header enableGraph={features.enable_graph} />
	<PageFrame>
		{@render children()}
	</PageFrame>
{:else}
	{@render children()}
{/if}

<style>
	.loading-screen {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.loading-text {
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-18);
	}
</style>
