/** Readable date formatting for Goodreads timestamps (ISO 8601 in, prose out). */

/** "4 August 2026" -- never a raw ISO string. */
export function formatDateLong(iso: string): string {
	const d = new Date(iso);
	return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

/** "3 days ago", falling back to a short absolute date once it's stale. */
export function formatRelative(iso: string): string {
	const then = new Date(iso).getTime();
	const diffMs = Date.now() - then;
	const diffMin = Math.round(diffMs / 60000);
	if (diffMin < 1) return 'just now';
	if (diffMin < 60) return `${diffMin} min ago`;
	const diffHr = Math.round(diffMin / 60);
	if (diffHr < 24) return `${diffHr} hr ago`;
	const diffDay = Math.round(diffHr / 24);
	if (diffDay < 7) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
	return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}
