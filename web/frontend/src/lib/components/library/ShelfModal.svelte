<script lang="ts">
	import { onMount } from 'svelte';
	import type { Book, SeriesSummary } from '$lib/types';
	import { getSeries, updateShelf, ApiError } from '$lib/api';
	import { seriesName } from '$lib/utils/series-name';

	const NEW_SERIES = '__new__';

	let {
		book,
		seriesId,
		onclose,
		onsaved,
	}: {
		book: Book;
		seriesId: string;
		onclose: () => void;
		onsaved: () => void;
	} = $props();

	let allSeries = $state<SeriesSummary[]>([]);
	let selectedSeries = $state<string>(seriesId);
	let newSeriesName = $state('');
	let bookOrder = $state<number>(book.book_order);
	let standalone = $state<boolean>(book.standalone);
	let saving = $state(false);
	let error = $state('');

	onMount(async () => {
		try {
			const res = await getSeries();
			allSeries = res.series;
		} catch {
			// non-fatal: the current series is already selected without the list
		}
	});

	const isNewSeries = $derived(selectedSeries === NEW_SERIES);
	const effectiveSeries = $derived(isNewSeries ? newSeriesName.trim() : selectedSeries);
	const isMoving = $derived(
		!standalone && (effectiveSeries !== seriesId || bookOrder !== book.book_order),
	);

	async function save() {
		error = '';
		saving = true;
		try {
			await updateShelf(book.id, {
				series_id: standalone ? seriesId : effectiveSeries,
				book_order: standalone ? book.book_order : bookOrder,
				standalone,
			});
			onsaved();
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not update shelf placement.';
		} finally {
			saving = false;
		}
	}
</script>

<div class="overlay">
	<button type="button" class="overlay-dismiss" aria-label="Close" onclick={onclose} disabled={saving}
	></button>
	<div class="modal" role="dialog" aria-modal="true" aria-label="Edit shelf placement for {book.title}">
		<h2 class="modal-title">{book.title}</h2>

		<fieldset class="field" disabled={saving || standalone}>
			<label class="small-caps" for="shelf-series">Series</label>
			<select id="shelf-series" bind:value={selectedSeries}>
				<option value={seriesId}>{seriesName(seriesId)}</option>
				{#each allSeries.filter((s) => s.id !== seriesId) as s (s.id)}
					<option value={s.id}>{seriesName(s.id)}</option>
				{/each}
				<option value={NEW_SERIES}>＋ new series…</option>
			</select>
		</fieldset>

		{#if isNewSeries && !standalone}
			<div class="field">
				<label class="small-caps" for="shelf-new-series">New series name</label>
				<input id="shelf-new-series" type="text" bind:value={newSeriesName} disabled={saving} />
			</div>
		{/if}

		<fieldset class="field" disabled={saving || standalone}>
			<label class="small-caps" for="shelf-order">Position in series</label>
			<input id="shelf-order" type="number" min="1" bind:value={bookOrder} />
		</fieldset>

		<label class="checkbox-row">
			<input type="checkbox" bind:checked={standalone} disabled={saving} />
			<span class="small-caps">This is a standalone book</span>
		</label>
		{#if standalone}
			<p class="explainer">A standalone sits on its own shelf, outside any series carousel.</p>
		{/if}

		{#if isMoving}
			<p class="warning">
				Changing this re-reads the book from its file — it takes a few seconds.
			</p>
		{/if}

		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}

		{#if saving}
			<div class="waiting">
				<div class="waiting-bar"><div class="waiting-fill"></div></div>
				<p class="waiting-copy">Saving shelf placement…</p>
			</div>
		{:else}
			<div class="modal-actions">
				<button class="btn-ghost small-caps" onclick={onclose}>Cancel</button>
				<button class="btn-primary small-caps" onclick={save}>Save</button>
			</div>
		{/if}
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
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		margin: 0 0 var(--sp-5);
		border: none;
		padding: 0;
	}
	.field label {
		color: var(--bone-muted);
	}
	.field:disabled,
	.field[disabled] {
		opacity: 0.5;
	}
	select,
	input[type='text'],
	input[type='number'] {
		background: var(--ink-bg);
		border: var(--hairline);
		color: var(--bone);
		padding: var(--sp-2);
		font-family: var(--serif-body);
		font-size: var(--fs-14);
		border-radius: var(--r-chip);
	}
	.checkbox-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		cursor: pointer;
		color: var(--bone);
		margin-bottom: var(--sp-2);
	}
	.explainer {
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--bone-muted);
		margin: 0 0 var(--sp-5);
	}
	.warning {
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--brass);
		margin: 0 0 var(--sp-5);
	}
	.error {
		color: var(--oxblood);
		font-size: var(--fs-14);
		margin-bottom: var(--sp-4);
	}
	.waiting {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
	}
	.waiting-bar {
		height: 2px;
		width: 100%;
		background: var(--ink-hairline);
		overflow: hidden;
		border-radius: 1px;
	}
	.waiting-fill {
		height: 100%;
		width: 40%;
		background: var(--brass);
		animation: sweep 1.6s ease-in-out infinite;
	}
	@keyframes sweep {
		0% {
			transform: translateX(-100%);
		}
		100% {
			transform: translateX(350%);
		}
	}
	.waiting-copy {
		font-style: italic;
		color: var(--bone-muted);
		font-size: var(--fs-14);
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
	/* --ink-bg is near-white in the light theme, so brass-on-ink-bg loses
	   contrast there -- --bone (near-black in light) reads correctly instead. */
	:global(:root[data-theme='light']) .btn-primary {
		color: var(--bone);
	}
</style>
