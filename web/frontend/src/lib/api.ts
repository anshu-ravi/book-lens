import type {
	CitationWindowResponse,
	CreateSessionResponse,
	CreditsResponse,
	LibraryResponse,
	PositionsResponse,
	SendMessageResponse,
	SeriesResponse,
	UndoResponse,
	UpdateProgressRequest,
	UpdateShelfRequest,
	UploadResponse,
	Book,
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

export function updateShelf(bookId: string, body: UpdateShelfRequest): Promise<Book> {
	return request<Book>(`/books/${bookId}/shelf`, {
		method: 'PUT',
		body: JSON.stringify(body),
	});
}

export function getSeries(): Promise<SeriesResponse> {
	return request<SeriesResponse>('/series');
}

export function uploadBook(
	file: File,
	series: string,
	bookOrder?: number,
	standalone?: boolean,
): Promise<UploadResponse> {
	const form = new FormData();
	form.append('file', file);
	form.append('series', series);
	if (bookOrder != null) form.append('book_order', String(bookOrder));
	if (standalone) form.append('standalone', 'true');
	return request<UploadResponse>('/upload', { method: 'POST', body: form });
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

export function deleteSession(sessionId: string): Promise<void> {
	return request<void>(`/chat/sessions/${sessionId}`, { method: 'DELETE' });
}

export function getCredits(): Promise<CreditsResponse> {
	return request<CreditsResponse>('/credits');
}
