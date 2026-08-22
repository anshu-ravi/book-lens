/** Converts a Goodreads shelf slug into a readable display name. */

const KNOWN: Record<string, string> = {
	'to-read': 'Want to Read',
	'currently-reading': 'Currently Reading',
	read: 'Read',
	'did-not-finish': 'Did Not Finish',
};

export function shelfLabel(slug: string): string {
	if (slug in KNOWN) return KNOWN[slug];
	return slug
		.split('-')
		.map((word) => (word.length > 0 ? word[0].toUpperCase() + word.slice(1) : word))
		.join(' ');
}
