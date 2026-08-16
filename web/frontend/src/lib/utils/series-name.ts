/** Display name for a series, whose API identity is a slug like `red-rising`. */
export function seriesName(seriesId: string): string {
	return seriesId
		.split(/[-_]/)
		.filter(Boolean)
		.map((word) => word[0].toUpperCase() + word.slice(1))
		.join(' ');
}
