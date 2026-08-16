<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { getLibrary, ApiError } from '$lib/api';
	import type { Book, SeriesGroup } from '$lib/types';
	import CurrentlyReadingCard from '$lib/components/library/CurrentlyReadingCard.svelte';
	import Carousel from '$lib/components/library/Carousel.svelte';
	import SeriesCard from '$lib/components/library/SeriesCard.svelte';
	import SeriesExpandedPanel from '$lib/components/library/SeriesExpandedPanel.svelte';
	import StandaloneCard from '$lib/components/library/StandaloneCard.svelte';
	import ProgressModal from '$lib/components/library/ProgressModal.svelte';

	let series = $state<SeriesGroup[]>([]);
	let loading = $state(true);
	let error = $state('');
	let expandedId = $state<string | null>(null);
	let modalBook = $state<Book | null>(null);

	const totalVolumes = $derived(series.reduce((n, s) => n + s.books.length, 0));
	const reading = $derived(
		series.flatMap((s) => s.books.filter((b) => b.status === 'reading').map((b) => ({ book: b, series: s }))),
	);

	// The API has no standalone flag: a SeriesGroup with more than one book is
	// a series, one with exactly one book is a standalone -- purely a convention.
	const multiBookSeries = $derived(series.filter((s) => s.books.length > 1));
	const standalones = $derived(
		series.filter((s) => s.books.length === 1).map((s) => ({ book: s.books[0], series: s })),
	);

	async function load() {
		loading = true;
		error = '';
		try {
			const res = await getLibrary();
			series = res.series;
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Could not load the library.';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function toggle(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function askAbout(book: Book) {
		goto(`/chat?book=${encodeURIComponent(book.id)}`);
	}

	function closeModal() {
		modalBook = null;
	}

	async function onSaved() {
		modalBook = null;
		await load();
	}
</script>

<svelte:head>
	<title>BookLens · Library</title>
</svelte:head>

{#if loading}
	<p class="loading-text">Opening the index…</p>
{:else if error}
	<p class="error-text">{error}</p>
{:else if series.length === 0}
	<div class="empty-state">
		<p>Nothing on the shelves yet.</p>
		<a href="/upload" class="small-caps">Add a volume →</a>
	</div>
{:else}
	<div class="greeting-strip">
		<span class="small-caps meta-line">
			Your library · {series.length} series · {totalVolumes} volumes
		</span>
		<h1 class="display-line">Where were we?</h1>
	</div>

	{#if reading.length > 0}
		<section class="section">
			<div class="section-header">
				<span class="small-caps">Currently reading</span>
				<div class="rule"></div>
			</div>
			<div class="reading-grid">
				{#each reading as { book, series: s } (book.id)}
					<CurrentlyReadingCard
						{book}
						series={s}
						onupdate={(b) => (modalBook = b)}
						onask={askAbout}
					/>
				{/each}
			</div>
		</section>
	{/if}

	<section class="section">
		<div class="section-header">
			<span class="small-caps">The shelf</span>
			<div class="rule"></div>
		</div>

		{#if multiBookSeries.length > 0}
			<div class="subsection">
				<span class="small-caps subsection-heading">Series</span>
				<Carousel>
					{#each multiBookSeries as s (s.id)}
						<SeriesCard series={s} expanded={expandedId === s.id} ontoggle={() => toggle(s.id)} />
					{/each}
				</Carousel>
				{#if expandedId}
					{#each multiBookSeries as s (s.id)}
						{#if s.id === expandedId}
							<SeriesExpandedPanel series={s} onupdate={(b) => (modalBook = b)} onask={askAbout} />
						{/if}
					{/each}
				{/if}
			</div>
		{/if}

		{#if standalones.length > 0}
			<div class="subsection">
				<span class="small-caps subsection-heading">Standalones</span>
				<Carousel>
					{#each standalones as { book, series: s } (book.id)}
						<StandaloneCard {book} series={s} onupdate={(b) => (modalBook = b)} onask={askAbout} />
					{/each}
				</Carousel>
			</div>
		{/if}
	</section>
{/if}

{#if modalBook}
	<ProgressModal book={modalBook} onclose={closeModal} onsaved={onSaved} />
{/if}

<style>
	.loading-text,
	.error-text {
		font-style: italic;
		color: var(--bone-muted);
	}
	.empty-state {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		align-items: flex-start;
		padding: var(--sp-16) 0;
	}
	.empty-state p {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-22);
		color: var(--bone-muted);
	}
	.empty-state a {
		color: var(--brass);
		text-decoration: none;
	}
	.greeting-strip {
		margin-bottom: var(--sp-12);
	}
	.meta-line {
		color: var(--brass);
		display: block;
		margin-bottom: var(--sp-2);
	}
	.display-line {
		font-family: var(--serif-display);
		font-style: italic;
		font-weight: 400;
		font-size: var(--fs-40);
		color: var(--bone);
		margin: 0;
	}
	.section {
		margin-bottom: var(--sp-12);
	}
	.section-header {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
		margin-bottom: var(--sp-6);
	}
	.section-header .small-caps {
		color: var(--bone);
		flex-shrink: 0;
	}
	.rule {
		flex: 1;
		height: 1px;
		background: var(--ink-hairline);
	}
	.reading-grid {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-12);
	}
	.subsection {
		margin-bottom: var(--sp-8);
	}
	.subsection-heading {
		display: block;
		color: var(--bone-muted);
		margin-bottom: var(--sp-4);
	}
</style>
