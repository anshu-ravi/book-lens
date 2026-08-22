<script lang="ts">
	import { onMount, tick } from 'svelte';
	import type { Book, BookStatus, Position, SeriesSummary } from '$lib/types';
	import { deleteBook, getPositions, getSeries, updateBook, updateProgress, ApiError } from '$lib/api';
	import { seriesName, slugify } from '$lib/utils/series-name';

	const NEW_SERIES = '__new__';

	let {
		book,
		seriesId,
		focus,
		onclose,
		onsaved,
	}: {
		book: Book;
		seriesId: string;
		focus: 'details' | 'reading';
		onclose: () => void;
		onsaved: () => void;
	} = $props();

	// Details section state
	let title = $state(book.title);
	let author = $state(book.author ?? '');
	let allSeries = $state<SeriesSummary[]>([]);
	let selectedSeries = $state<string>(seriesId);
	let newSeriesName = $state('');
	let bookOrder = $state<number>(book.book_order);
	let standalone = $state<boolean>(book.standalone);
	let titleError = $state('');

	// Reading section state
	let status = $state<BookStatus>(book.status);
	let chapterValue = $state<string>(book.status === 'reading' ? (book.position_ref ?? '') : '');
	let positions = $state<Position[] | null>(null);
	let loadingPositions = $state(false);

	let saving = $state(false);
	let error = $state('');
	let confirmingDelete = $state(false);
	let deleting = $state(false);

	let detailsSectionEl: HTMLElement | undefined = $state();
	let readingSectionEl: HTMLElement | undefined = $state();
	let titleInputEl: HTMLInputElement | undefined = $state();
	let unreadRadioEl: HTMLInputElement | undefined = $state();
	let readingRadioEl: HTMLInputElement | undefined = $state();
	let finishedRadioEl: HTMLInputElement | undefined = $state();

	onMount(async () => {
		try {
			const res = await getSeries();
			allSeries = res.series;
		} catch {
			// non-fatal: the current series is already selected without the list
		}
		await tick();
		if (focus === 'details') {
			titleInputEl?.focus();
			detailsSectionEl?.scrollIntoView({ block: 'nearest' });
		} else {
			const radioForStatus = { unread: unreadRadioEl, reading: readingRadioEl, finished: finishedRadioEl };
			radioForStatus[status]?.focus();
			readingSectionEl?.scrollIntoView({ block: 'nearest' });
		}
	});

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

	const isNewSeries = $derived(selectedSeries === NEW_SERIES);
	// Slugified, like the upload form does it: a typed "Red Rising" must land on
	// the same shelf as the existing `red-rising`, not beside it.
	const effectiveSeries = $derived(isNewSeries ? slugify(newSeriesName.trim()) : selectedSeries);

	const detailsChanged = $derived(
		title.trim() !== book.title ||
			(author.trim() || null) !== (book.author ?? null) ||
			standalone !== book.standalone ||
			(!standalone && (effectiveSeries !== seriesId || bookOrder !== book.book_order)),
	);
	const readingChanged = $derived(
		status !== book.status || (status === 'reading' && chapterValue !== (book.position_ref ?? '')),
	);

	async function save() {
		error = '';
		titleError = '';
		if (!title.trim()) {
			titleError = 'Title is required.';
			return;
		}
		if (!standalone && isNewSeries && !newSeriesName.trim()) {
			error = 'Name the new series, or pick an existing one.';
			return;
		}
		saving = true;
		try {
			if (detailsChanged) {
				await updateBook(book.id, {
					title: title.trim(),
					author: author.trim() || null,
					series_id: standalone ? seriesId : effectiveSeries,
					book_order: standalone ? book.book_order : bookOrder,
					standalone,
				});
			}
			if (readingChanged) {
				await updateProgress(book.id, {
					status,
					chapter: status === 'reading' ? chapterValue || null : null,
				});
			}
			onsaved();
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not save changes.';
		} finally {
			saving = false;
		}
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}

	async function confirmDelete() {
		error = '';
		deleting = true;
		try {
			await deleteBook(book.id);
			onsaved();
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not delete this book.';
			confirmingDelete = false;
		} finally {
			deleting = false;
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="overlay">
	<button type="button" class="overlay-dismiss" aria-label="Close" onclick={onclose} disabled={saving}
	></button>
	<div class="modal" role="dialog" aria-modal="true" aria-label="Edit {book.title}">
		<h2 class="modal-title">{book.title}</h2>

		<section class="modal-section" bind:this={detailsSectionEl}>
			<h3 class="section-heading small-caps">Details</h3>

			<div class="field">
				<label class="small-caps" for="edit-title">Title</label>
				<input id="edit-title" type="text" bind:value={title} bind:this={titleInputEl} disabled={saving} />
				{#if titleError}
					<p class="error" role="alert">{titleError}</p>
				{/if}
			</div>

			<div class="field">
				<label class="small-caps" for="edit-author">Author</label>
				<input id="edit-author" type="text" bind:value={author} disabled={saving} />
			</div>

			<label class="checkbox-row">
				<input type="checkbox" bind:checked={standalone} disabled={saving} />
				<span class="small-caps">This is a standalone book</span>
			</label>
			{#if standalone}
				<p class="explainer">A standalone sits on its own shelf, outside any series carousel.</p>
			{/if}

			{#if !standalone}
				<fieldset class="field" disabled={saving}>
					<label class="small-caps" for="edit-series">Series</label>
					<select id="edit-series" bind:value={selectedSeries}>
						<option value={seriesId}>{seriesName(seriesId)}</option>
						{#each allSeries.filter((s) => s.id !== seriesId) as s (s.id)}
							<option value={s.id}>{seriesName(s.id)}</option>
						{/each}
						<option value={NEW_SERIES}>＋ new series…</option>
					</select>
				</fieldset>

				{#if isNewSeries}
					<div class="field">
						<label class="small-caps" for="edit-new-series">New series name</label>
						<input id="edit-new-series" type="text" bind:value={newSeriesName} disabled={saving} />
					</div>
				{/if}

				<fieldset class="field" disabled={saving}>
					<label class="small-caps" for="edit-order">Position in series</label>
					<input id="edit-order" type="number" min="1" bind:value={bookOrder} />
				</fieldset>
			{/if}
		</section>

		<section class="modal-section" bind:this={readingSectionEl}>
			<h3 class="section-heading small-caps">Reading</h3>

			<fieldset class="status-group">
				<legend class="small-caps">Status</legend>
				<label class="radio-row">
					<input
						type="radio"
						name="status"
						value="unread"
						checked={status === 'unread'}
						bind:this={unreadRadioEl}
						onchange={() => (status = 'unread')}
					/>
					<span class="small-caps">unread</span>
				</label>
				<label class="radio-row">
					<input
						type="radio"
						name="status"
						value="reading"
						checked={status === 'reading'}
						bind:this={readingRadioEl}
						onchange={() => (status = 'reading')}
					/>
					<span class="small-caps">reading</span>
				</label>
				<label class="radio-row">
					<input
						type="radio"
						name="status"
						value="finished"
						checked={status === 'finished'}
						bind:this={finishedRadioEl}
						onchange={() => (status = 'finished')}
					/>
					<span class="small-caps">finished</span>
				</label>
			</fieldset>

			{#if status === 'finished'}
				<p class="status-hint">Marks the whole book read — the position moves to the last chapter.</p>
			{:else if status === 'unread'}
				<p class="status-hint">Clears your position back to the start.</p>
			{/if}

			{#if status === 'reading'}
				<div class="chapter-picker">
					<label class="small-caps" for="edit-chapter-select">Reading position</label>
					{#if loadingPositions}
						<p class="hint">Loading chapters…</p>
					{:else if positions}
						<select id="edit-chapter-select" bind:value={chapterValue}>
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
		</section>

		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}

		{#if confirmingDelete}
			<div class="modal-actions confirm-row">
				<p class="confirm-copy">Delete “{book.title}” and your progress? Your original file is untouched.</p>
				<div class="confirm-buttons">
					<button class="btn-ghost small-caps" onclick={() => (confirmingDelete = false)} disabled={deleting}>
						Keep
					</button>
					<button class="btn-danger small-caps" onclick={confirmDelete} disabled={deleting}>
						{deleting ? 'Deleting…' : 'Delete'}
					</button>
				</div>
			</div>
		{:else}
			<div class="modal-actions">
				<button
					class="btn-delete small-caps"
					onclick={() => (confirmingDelete = true)}
					disabled={saving}
				>
					Delete book
				</button>
				<div class="modal-actions-right">
					<button class="btn-ghost small-caps" onclick={onclose} disabled={saving}>Cancel</button>
					<button class="btn-primary small-caps" onclick={save} disabled={saving}>
						{saving ? 'Saving…' : 'Save'}
					</button>
				</div>
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
		z-index: 200;
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
		width: 460px;
		max-width: 100%;
		max-height: 85vh;
		overflow-y: auto;
	}
	.modal-title {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		margin: 0 0 var(--sp-6);
		color: var(--bone);
	}
	.modal-section {
		margin-bottom: var(--sp-6);
	}
	.section-heading {
		color: var(--brass);
		margin: 0 0 var(--sp-4);
		padding-bottom: var(--sp-2);
		border-bottom: var(--hairline);
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
	.status-group {
		border: none;
		padding: 0;
		margin: 0 0 var(--sp-3);
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
	.status-hint {
		font-style: italic;
		font-size: var(--fs-13);
		color: var(--bone-muted);
		margin: 0 0 var(--sp-5);
	}
	.chapter-picker {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}
	.chapter-picker label {
		color: var(--bone-muted);
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
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-4);
	}
	.modal-actions-right {
		display: flex;
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
	.btn-primary:disabled,
	.btn-ghost:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.btn-delete {
		background: none;
		border: none;
		padding: var(--sp-2) 0;
		color: var(--oxblood);
		cursor: pointer;
	}
	.btn-delete:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.confirm-row {
		flex-direction: column;
		align-items: stretch;
		gap: var(--sp-3);
	}
	.confirm-copy {
		color: var(--bone);
		font-size: var(--fs-14);
		margin: 0;
	}
	.confirm-buttons {
		display: flex;
		justify-content: flex-end;
		gap: var(--sp-4);
	}
	.btn-danger {
		padding: var(--sp-2) var(--sp-4);
		border-radius: var(--r-chip);
		cursor: pointer;
		background: var(--oxblood);
		border: 1px solid var(--oxblood);
		color: var(--bone);
	}
	.btn-danger:disabled {
		opacity: 0.6;
		cursor: default;
	}
</style>
