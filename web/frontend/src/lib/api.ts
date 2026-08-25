import type {
	CitationMarksResponse,
	CitationWindowResponse,
	CommitRequest,
	ConversationListResponse,
	ConversationMessageResponse,
	ConversationResponse,
	ConversationSummary,
	CommitResponse,
	CreateSessionResponse,
	CreditsResponse,
	InspectResponse,
	LibraryResponse,
	PositionsResponse,
	SendMessageResponse,
	SeriesResponse,
	UndoResponse,
	UpdateProgressRequest,
	UpdateBookRequest,
	Book,
	GoodreadsShelvesResponse,
	GoodreadsBooksResponse,
	GoodreadsSyncResponse,
	GoodreadsSettingsResponse,
	GoodreadsSettingsUpdate,
	GoodreadsStatsResponse,
	GoodreadsMatch,
	UnifiedLibraryResponse,
} from './types';

export class ApiError extends Error {
	constructor(
		public status: number,
		public detail: string,
	) {
		super(detail);
		this.name = 'ApiError';
	}
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
	const isFormData = init.body instanceof FormData;
	const headers: Record<string, string> = {
		...(isFormData ? {} : { 'Content-Type': 'application/json' }),
		...(init.headers as Record<string, string> | undefined),
	};

	let res: Response;
	try {
		res = await fetch(`/api${url}`, { ...init, headers });
	} catch (e) {
		if (e instanceof DOMException && e.name === 'AbortError') throw e;
		throw new ApiError(0, 'Could not reach the server. Is `booklens serve` running?');
	}

	if (!res.ok) {
		let detail = `HTTP ${res.status}`;
		try {
			const body = await res.json();
			detail = body.detail ?? detail;
		} catch {
			// ignore parse error, fall back to the status text
		}
		throw new ApiError(res.status, detail);
	}

	if (res.status === 204) return undefined as T;
	return (await res.json()) as T;
}

export function getLibrary(): Promise<LibraryResponse> {
	return request<LibraryResponse>('/library');
}

export function getPositions(bookId: string): Promise<PositionsResponse> {
	return request<PositionsResponse>(`/books/${bookId}/positions`);
}

export function updateProgress(bookId: string, body: UpdateProgressRequest): Promise<Book> {
	return request<Book>(`/books/${bookId}/progress`, {
		method: 'PUT',
		body: JSON.stringify(body),
	});
}

export function updateBook(bookId: string, body: UpdateBookRequest): Promise<Book> {
	return request<Book>(`/books/${bookId}`, {
		method: 'PUT',
		body: JSON.stringify(body),
	});
}

export function getSeries(): Promise<SeriesResponse> {
	return request<SeriesResponse>('/series');
}

export function inspectUpload(file: File): Promise<InspectResponse> {
	const form = new FormData();
	form.append('file', file);
	return request<InspectResponse>('/upload/inspect', { method: 'POST', body: form });
}

export function inspectCoverUrl(sha256: string): string {
	return `/api/upload/inspect/${encodeURIComponent(sha256)}/cover`;
}

export function commitUpload(body: CommitRequest): Promise<CommitResponse> {
	return request<CommitResponse>('/upload/commit', { method: 'POST', body: JSON.stringify(body) });
}

export function createChatSession(bookId: string): Promise<CreateSessionResponse> {
	return request<CreateSessionResponse>('/chat/sessions', {
		method: 'POST',
		body: JSON.stringify({ book_id: bookId }),
	});
}

export function sendMessage(
	sessionId: string,
	question: string,
	signal?: AbortSignal,
): Promise<SendMessageResponse> {
	return request<SendMessageResponse>(`/chat/sessions/${sessionId}/messages`, {
		method: 'POST',
		body: JSON.stringify({ question }),
		signal,
	});
}

export function undoTurn(sessionId: string): Promise<UndoResponse> {
	return request<UndoResponse>(`/chat/sessions/${sessionId}/undo`, { method: 'POST' });
}

export function getCitationWindow(
	sessionId: string,
	citationId: string,
	windowSize = 3,
): Promise<CitationWindowResponse> {
	return request<CitationWindowResponse>(
		`/chat/sessions/${sessionId}/citations/${encodeURIComponent(citationId)}?window=${windowSize}`,
	);
}

export function getCitationMarks(
	sessionId: string,
	citationIds: string[],
): Promise<CitationMarksResponse> {
	return request<CitationMarksResponse>(`/chat/sessions/${sessionId}/citation-marks`, {
		method: 'POST',
		body: JSON.stringify({ citation_ids: citationIds }),
	});
}

export function deleteSession(sessionId: string): Promise<void> {
	return request<void>(`/chat/sessions/${sessionId}`, { method: 'DELETE' });
}

export function listConversations(): Promise<ConversationListResponse> {
	return request<ConversationListResponse>('/chat/conversations');
}

/** Names a conversation, adopting the draft session the page already opened. */
export function newConversation(
	bookId: string,
	sessionId?: string,
): Promise<ConversationResponse> {
	return request<ConversationResponse>('/chat/conversations', {
		method: 'POST',
		body: JSON.stringify({ book_id: bookId, session_id: sessionId ?? null }),
	});
}

export function openConversation(conversationId: string): Promise<ConversationResponse> {
	return request<ConversationResponse>(`/chat/conversations/${conversationId}`);
}

export function askInConversation(
	conversationId: string,
	question: string,
	signal?: AbortSignal,
): Promise<ConversationMessageResponse> {
	return request<ConversationMessageResponse>(`/chat/conversations/${conversationId}/messages`, {
		method: 'POST',
		body: JSON.stringify({ question }),
		signal,
	});
}

export function undoConversationTurn(conversationId: string): Promise<{ ok: boolean }> {
	return request<{ ok: boolean }>(`/chat/conversations/${conversationId}/undo`, { method: 'POST' });
}

export function renameConversation(conversationId: string, title: string) {
	return request<ConversationSummary>(`/chat/conversations/${conversationId}`, {
		method: 'PATCH',
		body: JSON.stringify({ title }),
	});
}

export function deleteConversation(conversationId: string): Promise<void> {
	return request<void>(`/chat/conversations/${conversationId}`, { method: 'DELETE' });
}

export function getCredits(): Promise<CreditsResponse> {
	return request<CreditsResponse>('/credits');
}

export function deleteBook(bookId: string): Promise<void> {
	return request<void>(`/books/${encodeURIComponent(bookId)}`, { method: 'DELETE' });
}

export function getGoodreadsShelves(): Promise<GoodreadsShelvesResponse> {
	return request<GoodreadsShelvesResponse>('/goodreads/shelves');
}

export function getGoodreadsBooks(shelf: string): Promise<GoodreadsBooksResponse> {
	return request<GoodreadsBooksResponse>(`/goodreads/books?shelf=${encodeURIComponent(shelf)}`);
}

export function syncGoodreads(): Promise<GoodreadsSyncResponse> {
	return request<GoodreadsSyncResponse>('/goodreads/sync', {
		method: 'POST',
		body: JSON.stringify({}),
	});
}

export function getGoodreadsSettings(): Promise<GoodreadsSettingsResponse> {
	return request<GoodreadsSettingsResponse>('/goodreads/settings');
}

export function putGoodreadsSettings(
	body: GoodreadsSettingsUpdate,
): Promise<GoodreadsSettingsResponse> {
	return request<GoodreadsSettingsResponse>('/goodreads/settings', {
		method: 'PUT',
		body: JSON.stringify(body),
	});
}

export function getGoodreadsStats(): Promise<GoodreadsStatsResponse> {
	return request<GoodreadsStatsResponse>('/goodreads/stats');
}

export function getGoodreadsBook(goodreadsBookId: string): Promise<GoodreadsMatch> {
	return request<GoodreadsMatch>(`/goodreads/books/${encodeURIComponent(goodreadsBookId)}`);
}

export function getUnifiedLibrary(): Promise<UnifiedLibraryResponse> {
	return request<UnifiedLibraryResponse>('/library/unified');
}

export function linkBook(bookId: string, goodreadsBookId: string): Promise<{ book_id: string; goodreads_book_id: string | null }> {
	return request(`/library/link`, {
		method: 'POST',
		body: JSON.stringify({ book_id: bookId, goodreads_book_id: goodreadsBookId }),
	});
}

export function unlinkBook(bookId: string): Promise<{ book_id: string; goodreads_book_id: string | null }> {
	return request(`/library/link/${encodeURIComponent(bookId)}`, { method: 'DELETE' });
}
