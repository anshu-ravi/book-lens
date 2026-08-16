/** Display name for a series, whose API identity is a slug like `red-rising`. */
export function seriesName(seriesId: string): string {
	return seriesId
		.split(/[-_]/)
		.filter(Boolean)
		.map((word) => word[0].toUpperCase() + word.slice(1))
		.join(' ');
}

/** A book title turned into a series id, for a standalone book's own one-book "series". */
export function slugify(title: string): string {
	return (
		title
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '') || 'book'
	);
}
