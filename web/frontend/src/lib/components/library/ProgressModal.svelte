<script lang="ts">
	import type { Book, BookStatus, Position } from '$lib/types';
	import { getPositions, updateProgress, ApiError } from '$lib/api';

	let {
		book,
		onclose,
		onsaved,
	}: {
		book: Book;
		onclose: () => void;
		onsaved: () => void;
	} = $props();

	let status = $state<BookStatus>(book.status);
	let chapterValue = $state<string>(
		book.status === 'reading' ? (book.position_ref ?? '') : '',
	);
	let positions = $state<Position[] | null>(null);
	let loadingPositions = $state(false);
	let saving = $state(false);
	let error = $state('');

	function positionKey(p: Position): string {
		if ('number' in p) return String(p.number);
		if ('name' in p) return p.name;
		return '';
	}

	function positionDisplay(p: Position): string {
		if ('number' in p) return p.label ? `${p.number} — ${p.label}` : String(p.number);
		if ('name' in p) return p.label ? `${p.name} — ${p.label}` : p.name;
		return '';
	}

	$effect(() => {
		if (status === 'reading' && positions === null && !loadingPositions) {
			loadingPositions = true;
			getPositions(book.id)
				.then((res) => {
					positions = res.positions;
				})
				.catch((e) => {
					error = e instanceof ApiError ? e.detail : 'Could not load chapter list.';
				})
				.finally(() => {
					loadingPositions = false;
				});
		}
	});

	async function save() {
		error = '';
		saving = true;
		try {
			await updateProgress(book.id, {
				status,
				chapter: status === 'reading' ? chapterValue || null : null,
			});
			onsaved();
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not save progress.';
		} finally {
			saving = false;
		}
	}

	// group positions into part-delimited sections for optgroups
	type Group = { label: string | null; items: Position[] };
	const groups = $derived.by<Group[]>(() => {
		if (!positions) return [];
		const result: Group[] = [];
		let current: Group = { label: null, items: [] };
		for (const p of positions) {
			if ('part' in p) {
				if (current.items.length) result.push(current);
				current = { label: p.part, items: [] };
			} else {
				current.items.push(p);
			}
		}
		if (current.items.length) result.push(current);
		return result;
	});
</script>

<div class="overlay">
	<button type="button" class="overlay-dismiss" aria-label="Close" onclick={onclose}></button>
	<div class="modal" role="dialog" aria-modal="true" aria-label="Update progress for {book.title}">
		<h2 class="modal-title">{book.title}</h2>

		<fieldset class="status-group">
			<legend class="small-caps">Status</legend>
			{#each (['unread', 'reading', 'finished'] as BookStatus[]) as s}
				<label class="radio-row">
					<input type="radio" name="status" value={s} checked={status === s} onchange={() => (status = s)} />
					<span class="small-caps">{s}</span>
				</label>
			{/each}
		</fieldset>

		{#if status === 'reading'}
			<div class="chapter-picker">
				<label class="small-caps" for="chapter-select">Reading position</label>
				{#if loadingPositions}
					<p class="hint">Loading chapters…</p>
				{:else if positions}
					<select id="chapter-select" bind:value={chapterValue}>
						<option value="">Choose a chapter…</option>
						{#each groups as group}
							{#if group.label}
								<optgroup label={group.label}>
									{#each group.items as p}
										<option value={positionKey(p)}>{positionDisplay(p)}</option>
									{/each}
								</optgroup>
							{:else}
								{#each group.items as p}
									<option value={positionKey(p)}>{positionDisplay(p)}</option>
								{/each}
							{/if}
						{/each}
					</select>
				{/if}
			</div>
		{/if}

		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}

		<div class="modal-actions">
			<button class="btn-ghost small-caps" onclick={onclose} disabled={saving}>Cancel</button>
			<button class="btn-primary small-caps" onclick={save} disabled={saving}>
				{saving ? 'Saving…' : 'Save'}
			</button>
		</div>
	</div>
</div>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 100;
		padding: var(--sp-4);
	}
	.overlay-dismiss {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		border: none;
		padding: 0;
		background: color-mix(in srgb, var(--ink-bg) 80%, transparent);
		cursor: default;
	}
	.modal {
		position: relative;
		background: var(--ink-surface);
		border: var(--hairline);
		border-radius: var(--r-cover);
		padding: var(--sp-8);
		width: 420px;
		max-width: 100%;
	}
	.modal-title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		margin: 0 0 var(--sp-6);
		color: var(--bone);
	}
	.status-group {
		border: none;
		padding: 0;
		margin: 0 0 var(--sp-6);
		display: flex;
		gap: var(--sp-6);
	}
	.status-group legend {
		color: var(--bone-muted);
		margin-bottom: var(--sp-2);
	}
	.radio-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		cursor: pointer;
		color: var(--bone);
	}
	.chapter-picker {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		margin-bottom: var(--sp-6);
	}
	.chapter-picker label {
		color: var(--bone-muted);
	}
	select {
		background: var(--ink-bg);
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-2);
		font-family: var(--serif-body);
		font-size: var(--fs-14);
		border-radius: var(--r-chip);
	}
	.hint {
		color: var(--bone-muted);
		font-style: italic;
		font-size: var(--fs-14);
	}
	.error {
		color: var(--oxblood);
		font-size: var(--fs-14);
		margin-bottom: var(--sp-4);
	}
	.modal-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--sp-4);
	}
	.btn-ghost,
	.btn-primary {
		padding: var(--sp-2) var(--sp-4);
		border-radius: var(--r-chip);
		cursor: pointer;
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
	.btn-primary:disabled,
	.btn-ghost:disabled {
		opacity: 0.6;
		cursor: default;
	}
</style>
