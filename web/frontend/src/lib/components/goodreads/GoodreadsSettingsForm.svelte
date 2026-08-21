<script lang="ts">
	import { putGoodreadsSettings, ApiError } from '$lib/api';
	import type { GoodreadsSettingsResponse } from '$lib/types';

	let {
		initialUserId = '',
		initialDnfShelf = '',
		onSave,
		onCancel,
	}: {
		initialUserId?: string;
		initialDnfShelf?: string;
		onSave: (settings: GoodreadsSettingsResponse) => void;
		onCancel?: () => void;
	} = $props();

	let userIdInput = $state(initialUserId);
	let dnfInput = $state(initialDnfShelf);
	let formError = $state('');
	let saving = $state(false);

	async function submit() {
		formError = '';
		if (!userIdInput.trim()) {
			formError = 'Enter a Goodreads profile URL or numeric user id.';
			return;
		}
		saving = true;
		try {
			const settings = await putGoodreadsSettings({
				user_id: userIdInput.trim(),
				dnf_shelf: dnfInput.trim() || null,
			});
			onSave(settings);
		} catch (e) {
			formError = e instanceof ApiError ? e.detail : 'Could not save Goodreads settings.';
		} finally {
			saving = false;
		}
	}
</script>

<form
	class="settings-form"
	onsubmit={(e) => {
		e.preventDefault();
		submit();
	}}
>
	<div class="field">
		<label class="small-caps" for="gr-user-id">Goodreads profile URL or user ID</label>
		<input
			id="gr-user-id"
			type="text"
			bind:value={userIdInput}
			disabled={saving}
			placeholder="https://www.goodreads.com/user/show/12345-you"
		/>
	</div>
	<div class="field">
		<label class="small-caps" for="gr-dnf-shelf">Did-not-finish shelf name (optional)</label>
		<input
			id="gr-dnf-shelf"
			type="text"
			bind:value={dnfInput}
			disabled={saving}
			placeholder="did-not-finish"
		/>
	</div>
	{#if formError}
		<p class="form-error" role="alert">{formError}</p>
	{/if}
	<div class="form-actions">
		{#if onCancel}
			<button type="button" class="btn-ghost small-caps" onclick={onCancel} disabled={saving}>
				Cancel
			</button>
		{/if}
		<button type="submit" class="btn-primary small-caps" disabled={saving}>
			{saving ? 'Saving…' : 'Save & sync'}
		</button>
	</div>
</form>

<style>
	.settings-form {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		padding: var(--sp-3);
		margin-top: var(--sp-2);
		border: var(--hairline);
		border-radius: var(--r-chip);
		background: var(--ink-surface);
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}
	.field label {
		color: var(--bone-muted);
		font-size: var(--fs-12);
	}
	input[type='text'] {
		background: var(--ink-bg);
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-2);
		font-family: var(--serif-body);
		font-size: var(--fs-13);
		border-radius: var(--r-chip);
		width: 100%;
		box-sizing: border-box;
	}
	.form-error {
		color: var(--oxblood);
		font-size: var(--fs-12);
		margin: 0;
	}
	.form-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--sp-2);
	}
	.btn-ghost,
	.btn-primary {
		padding: var(--sp-1) var(--sp-3);
		border-radius: var(--r-chip);
		cursor: pointer;
		font-size: var(--fs-12);
	}
	.btn-ghost {
		background: none;
		border: var(--hairline);
		color: var(--bone-muted);
	}
	.btn-primary {
		background: var(--brass);
		border: 1px solid var(--brass);
		color: var(--ink-bg);
	}
	/* --ink-bg is near-white in the light theme, so brass-on-ink-bg loses
	   contrast there -- --bone (near-black in light) reads correctly instead. */
	:global(:root[data-theme='light']) .btn-primary {
		color: var(--bone);
	}
	.btn-ghost:disabled,
	.btn-primary:disabled {
		opacity: 0.6;
		cursor: default;
	}
</style>
