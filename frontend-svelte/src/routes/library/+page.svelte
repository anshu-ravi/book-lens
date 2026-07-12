<script lang="ts">
	import libraryStore, { refreshLibrary } from '$lib/stores/library.svelte';
	import { deleteBook, updateBookStatus } from '$lib/api/library';
	import auth from '$lib/stores/auth.svelte';
	import type { Book, BookStatus, Series } from '$lib/types';

	import GreetingStrip from '$lib/components/library/GreetingStrip.svelte';
	import SectionHeader from '$lib/components/library/SectionHeader.svelte';
	import Carousel from '$lib/components/library/Carousel.svelte';
	import CurrentlyReadingCard from '$lib/components/library/CurrentlyReadingCard.svelte';
	import IndexFilter from '$lib/components/library/IndexFilter.svelte';
	import SeriesTable from '$lib/components/library/SeriesTable.svelte';
	import StandaloneCarousel from '$lib/components/library/StandaloneCarousel.svelte';
	import BookEditModal from '$lib/components/library/BookEditModal.svelte';
	import { toRoman } from '$lib/utils/roman';

	$effect(() => {
		if (!libraryStore.data && !libraryStore.loading) refreshLibrary();
	});

	// --- Derived collections ---
	const allBooks = $derived(libraryStore.data?.series.flatMap(s => s.books.map(b => ({ book: b, series: s }))) ?? []);

	const currentlyReading = $derived(allBooks.filter(({ book }) => book.status === 'reading'));

	const seriesList = $derived(
		(libraryStore.data?.series ?? []).filter(s =>
			s.books.some(b => b.is_series) || s.books.length > 1
		)
	);

	const standalones = $derived(
		allBooks.filter(({ book }) => !book.is_series)
	);

	const sortedSeries = $derived([...seriesList].sort((a, b) => a.name.localeCompare(b.name)));

	// --- UI state ---
	let filter = $state<'series' | 'standalone'>('series');
	let modalBook = $state<{ book: Book; series: Series } | null>(null);

	const indexLabel = $derived(filter === 'standalone' ? 'INDEX OF STANDALONES' : 'INDEX OF SERIES');
	const crCount = $derived(toRoman(currentlyReading.length));

	// --- Modal handlers ---
	function openModal(book: Book, series: Series) {
		modalBook = { book, series };
	}

	function closeModal() {
		modalBook = null;
	}

	async function handleModalSave(bookId: string, status: BookStatus, chapter: number | undefined) {
		await updateBookStatus(bookId, {
			status,
			current_chapter_index: chapter,
		});
		await refreshLibrary();
	}

	async function handleModalDelete(bookId: string) {
		await deleteBook(bookId);
		await refreshLibrary();
	}
</script>

{#if libraryStore.loading}
	<div class="loading">
		<span>Opening the shelves…</span>
	</div>
{:else if libraryStore.error}
	<div class="error">{libraryStore.error}</div>
{:else if auth.user && libraryStore.data}

	<GreetingStrip user={auth.user} library={libraryStore.data} />

	<!-- Currently Reading -->
	{#if currentlyReading.length > 0}
		<section class="section">
			<SectionHeader
				label="Currently Reading"
				gloss="— pick up where you left off"
				count="· {crCount} {currentlyReading.length === 1 ? 'BOOK' : 'BOOKS'} ·"
			/>
			<Carousel>
				{#each currentlyReading as { book, series } (book.id)}
					<CurrentlyReadingCard {book} {series} onbookclick={openModal} />
				{/each}
			</Carousel>
		</section>
	{/if}

	<!-- Index of Series / Standalones -->
	<section class="section">
		<div class="index-controls">
			<IndexFilter bind:value={filter} />
			<SectionHeader label={indexLabel} gloss="— all the shelves; hover to draw a cover" />
		</div>

		{#if filter === 'series'}
			{#if sortedSeries.length === 0}
				<p class="empty">No series in your library yet. <a href="/upload">Upload a volume.</a></p>
			{:else}
				<SeriesTable series={sortedSeries} onbookclick={openModal} />
			{/if}
		{:else}
			<StandaloneCarousel books={standalones} onbookclick={openModal} />
		{/if}
	</section>

{/if}

{#if modalBook}
	<BookEditModal
		book={modalBook.book}
		series={modalBook.series}
		onclose={closeModal}
		onsave={handleModalSave}
		ondelete={handleModalDelete}
	/>
{/if}

<style>
	.loading, .error {
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--bone-muted);
		padding: var(--sp-12) 0;
	}
	.error { color: var(--oxblood); }

	.section { margin-bottom: var(--sp-12); }

	.index-controls { margin-bottom: var(--sp-4); }

	.empty {
		font-family: var(--serif-body);
		font-style: italic;
		color: var(--bone-muted);
		padding: var(--sp-8) 0;
	}
	.empty a { color: var(--brass); }
</style>
