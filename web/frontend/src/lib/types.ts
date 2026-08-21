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
}

export interface CommitRequest {
	sha256: string;
	title: string | null;
	author: string | null;
	series_id: string;
	book_order: number;
	standalone: boolean;
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
}

export interface CreateSessionRequest {
	book_id: string;
}

export interface CreateSessionResponse {
	session_id: string;
	book_id: string;
	book_title: string;
	prior_titles: string[];
	chapter_label: string;
	para_count: number;
	token_estimate: number;
}

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
