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
}

export interface SeriesGroup {
	id: string;
	books: Book[];
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

export interface UploadResponse {
	book_id: string;
	title: string;
	author: string;
	book_order: number;
	series_id: string;
	chapters: number;
	paragraphs: number;
	skipped: number;
	excerpt_chapters: ExcerptChapter[];
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
