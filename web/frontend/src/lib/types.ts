/** Mirror of the backend API contract. Keep in sync with the FastAPI app under booklens/web. */

export type BookStatus = 'unread' | 'reading' | 'finished';

export interface Book {
	id: string;
	title: string;
	author: string;
	book_order: number;
	status: BookStatus;
	position_chapter_idx: number | null;
	/** The reader-facing reference for the position ("20", "prologue"), not the internal index. */
	position_ref: string | null;
	position_label: string | null;
	chapter_count: number;
	chapters_read: number;
	percent: number;
	has_cover: boolean;
	standalone: boolean;
}

export interface SeriesGroup {
	id: string;
	books: Book[];
	standalone: boolean;
}

export interface LibraryResponse {
	series: SeriesGroup[];
}

export interface PartPosition {
	part: string;
}

export interface ChapterPosition {
	number: number;
	label?: string;
}

export interface NamedPosition {
	name: string;
	label?: string;
}

export type Position = PartPosition | ChapterPosition | NamedPosition;

export interface PositionsResponse {
	book: Book;
	positions: Position[];
}

export interface UpdateProgressRequest {
	status: BookStatus;
	chapter: string | null;
}

export interface UpdateBookRequest {
	title: string;
	author: string | null;
	series_id: string;
	book_order: number;
	standalone: boolean;
}

export interface SeriesSummary {
	id: string;
	book_count: number;
	next_order: number;
}

export interface SeriesResponse {
	series: SeriesSummary[];
}

export interface ExcerptChapter {
	label: string;
	paragraphs: number;
}

export interface GoodreadsMatch {
	goodreads_book_id: string;
	title: string;
	author: string | null;
	series: string | null;
	series_number: number | null;
	cover: string | null;
	num_pages: number | null;
	description: string | null;
	goodreads_url: string;
	linked_book_id: string | null;
}

export interface InspectResponse {
	sha256: string;
	filename: string;
	size_bytes: number;
	title: string;
	author: string | null;
	chapters_detected: number;
	has_prologue: boolean;
	has_cover: boolean;
	suggested_series_id: string | null;
	suggested_series_name: string | null;
	prior_volumes: number;
	suggested_book_order: number;
	already_ingested: boolean;
	existing_book_id: string | null;
	goodreads_match: GoodreadsMatch | null;
}

export interface CommitRequest {
	sha256: string;
	title: string | null;
	author: string | null;
	series_id: string;
	book_order: number;
	standalone: boolean;
	goodreads_book_id?: string | null;
}

export interface CommitResponse {
	book_id: string;
	title: string;
	author: string;
	book_order: number;
	series_id: string;
	chapters: number;
	paragraphs: number;
	skipped: boolean;
	excerpt_chapters: ExcerptChapter[];
	standalone: boolean;
	goodreads_book_id?: string | null;
}

export interface CreateSessionRequest {
	book_id: string;
}

/** `POST /chat/sessions` returns the same header a conversation does, minus the transcript. */
export type CreateSessionResponse = SessionHeader;

export interface SendMessageRequest {
	question: string;
}

export interface MessageDebug {
	context_tokens: number;
	prompt_tokens: number;
	cached_tokens: number;
	cache_write_tokens: number;
	turn_cost_usd: number;
	session_cost_usd: number;
}

export interface SendMessageResponse {
	answer: string;
	citations: string[];
	debug: MessageDebug;
}

export interface ConversationSummary {
	id: string;
	book_id: string;
	title: string;
	chapter_idx: number;
	chapter_label: string;
	turn_count: number;
	created_at: string;
	updated_at: string;
}

export interface ConversationGroup {
	book_id: string;
	book_title: string;
	book_author: string | null;
	series_id: string;
	book_order: number;
	conversations: ConversationSummary[];
}

export interface ConversationListResponse {
	groups: ConversationGroup[];
}

/** The header every chat screen carries: which volumes are in context, and where the ceiling sits. */
export interface SessionHeader {
	session_id: string;
	book_id: string;
	book_title: string;
	book_author: string | null;
	series_id: string;
	prior_books: { id: string; title: string }[];
	prior_titles: string[];
	chapter_idx: number;
	chapter_label: string;
	chapter_count: number;
	chapter_position: number;
	para_count: number;
	token_estimate: number;
}

export interface StoredTurn {
	question: string;
	answer: string;
	citations: string[];
	chapter_idx: number;
	chapter_label: string;
	created_at: string;
}

export interface ConversationResponse extends SessionHeader {
	conversation: ConversationSummary;
	turns: StoredTurn[];
	started_at_chapter_idx: number;
	started_at_chapter_label: string;
	moved_on: boolean;
}

export interface ConversationMessageResponse extends SendMessageResponse {
	session_id: string;
	chapter_idx: number;
	chapter_label: string;
	conversation: ConversationSummary;
}

export interface CitationMark {
	id: string;
	book_id: string;
	chapter_label: string;
	/** Where the paragraph sits in its own book, 0 at the first page and 1 at the last. */
	fraction: number;
}

export interface CitationMarksResponse {
	marks: CitationMark[];
}

export interface UndoResponse {
	ok: boolean;
	turns: number;
}

export interface CitationParagraph {
	citation_id: string;
	chapter: string;
	text: string;
}

export interface CitationWindowResponse {
	citation_id: string;
	paragraphs: CitationParagraph[];
}

export interface CreditsResponse {
	limit: number;
	limit_remaining: number;
	usage: number;
	usage_daily: number;
	usage_weekly: number;
	usage_monthly: number;
}

export interface UnifiedProgress {
	status: BookStatus;
	chapter_idx: number | null;
	ceiling_seq: number;
}

export interface UnifiedEntry {
	goodreads_book_id: string | null;
	title: string;
	display_title: string;
	author: string;
	cover: string | null;
	series: string | null;
	series_number: number | null;
	user_rating: number | null;
	average_rating: number | null;
	num_pages: number | null;
	description: string | null;
	genres: string[];
	date_added: string | null;
	date_started: string | null;
	date_read: string | null;
	goodreads_url: string | null;
	book_id: string | null;
	askable: boolean;
	progress: UnifiedProgress | null;
}

export interface UnifiedGroup {
	series: string | null;
	books: UnifiedEntry[];
}

export interface UnifiedShelf {
	shelf: string;
	label: string;
	count: number;
	groups: UnifiedGroup[];
}

export interface UnifiedLibraryResponse {
	shelves: UnifiedShelf[];
	totals: { books: number; with_epub: number; askable: number };
}

export interface GoodreadsShelf {
	shelf: string;
	count: number;
	truncated: boolean;
}

export interface GoodreadsShelvesResponse {
	shelves: GoodreadsShelf[];
	total: number;
	synced_at: string | null;
}

export interface GoodreadsBook {
	review_id: string;
	book_id: string;
	title: string;
	author: string;
	isbn: string | null;
	num_pages: number | null;
	published_year: number | null;
	description: string | null;
	cover_small: string | null;
	cover_medium: string | null;
	cover_large: string | null;
	average_rating: number | null;
	user_rating: number | null;
	user_review: string | null;
	shelf: string;
	custom_shelves: string[];
	date_added: string | null;
	date_read: string | null;
	date_created: string | null;
	date_started: string | null;
	goodreads_url: string | null;
}

export interface GoodreadsBooksResponse {
	books: GoodreadsBook[];
}

export interface GoodreadsSyncResponse {
	shelf_counts: Record<string, number>;
	truncated_shelves: string[];
	total_books: number;
}

export interface GoodreadsSettingsResponse {
	user_id: string | null;
	dnf_shelf: string | null;
	source: 'stored' | 'env' | 'none';
}

export interface GoodreadsSettingsUpdate {
	user_id: string;
	dnf_shelf: string | null;
}

export interface GoodreadsStatsTotals {
	books_read: number;
	pages_read: number;
	avg_pages: number;
	dnf: number;
	want_to_read: number;
	currently_reading: number;
	backlog_pages: number;
	longest: { title: string; num_pages: number } | null;
	shortest: { title: string; num_pages: number } | null;
}

export interface GoodreadsStatsCoverage {
	read_total: number;
	with_date_read: number;
	with_date_started?: number;
	with_genres?: number;
}

export interface GoodreadsStatsMonthBook {
	goodreads_book_id: string;
	title: string;
	author: string | null;
	series: string | null;
	series_number: number | null;
	cover: string | null;
	pages: number | null;
	rating: number | null;
	date_read: string | null;
}

export interface GoodreadsStatsMonth {
	month: string;
	count: number;
	pages: number;
	books: GoodreadsStatsMonthBook[];
}

export interface GoodreadsStatsAuthor {
	author: string;
	books: number;
}

export interface GoodreadsStatsDecade {
	decade: number;
	books: number;
}

export interface GoodreadsStatsSeries {
	name: string;
	read: number;
	total: number;
	shelves: string[];
}

export interface GoodreadsStatsDurationBook {
	title: string;
	days: number;
	pages: number;
	rating: number;
}

export interface GoodreadsStatsDurations {
	count: number;
	median_days: number;
	mean_days: number;
	fastest: { title: string; days: number } | null;
	slowest: { title: string; days: number } | null;
	books: GoodreadsStatsDurationBook[];
}

export interface GoodreadsStatsGenre {
	genre: string;
	books: number;
}

export interface GoodreadsStatsGenreRating {
	genre: string;
	avg_rating: number;
	books: number;
}

export interface GoodreadsStatsResponse {
	totals: GoodreadsStatsTotals;
	coverage: GoodreadsStatsCoverage;
	by_month: GoodreadsStatsMonth[];
	top_authors: GoodreadsStatsAuthor[];
	by_decade: GoodreadsStatsDecade[];
	series: GoodreadsStatsSeries[];
	durations?: GoodreadsStatsDurations;
	genres?: GoodreadsStatsGenre[];
	rating_by_genre?: GoodreadsStatsGenreRating[];
}
