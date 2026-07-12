<script lang="ts">
	import { goto } from '$app/navigation';
	import { getSupabase } from '$lib/supabase';
	import auth from '$lib/stores/auth.svelte';

	let email = $state('');
	let password = $state('');
	let loading = $state(false);
	let error = $state('');
	let info = $state('');

	$effect(() => {
		if (auth.ready && auth.user) goto('/library');
	});

	async function login() {
		loading = true;
		error = '';
		info = '';
		try {
			const { error: err } = await getSupabase().auth.signInWithPassword({ email, password });
			if (err) error = err.message;
			else goto('/library');
		} finally {
			loading = false;
		}
	}

	async function signUp() {
		loading = true;
		error = '';
		info = '';
		try {
			const { data, error: err } = await getSupabase().auth.signUp({ email, password });
			if (err) error = err.message;
			else if (data.user && !data.session) info = 'Check your email for a confirmation link!';
			else goto('/library');
		} finally {
			loading = false;
		}
	}
</script>

<h1>BookLens</h1>
{#if error}<p style="color:red">{error}</p>{/if}
{#if info}<p style="color:green">{info}</p>{/if}

<label>Email<br /><input type="email" bind:value={email} /></label><br />
<label>Password<br /><input type="password" bind:value={password} /></label><br /><br />

<button onclick={login} disabled={loading}>Sign in</button>
<button onclick={signUp} disabled={loading}>Sign up</button>
