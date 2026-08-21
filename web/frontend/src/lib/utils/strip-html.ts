/** Turns a remote HTML blurb into plain-text paragraphs, safe to render without {@html}. */

const ENTITIES: Record<string, string> = {
	amp: '&',
	lt: '<',
	gt: '>',
	quot: '"',
	apos: "'",
	nbsp: ' ',
	mdash: '—',
	ndash: '–',
	hellip: '…',
	rsquo: '’',
	lsquo: '‘',
	rdquo: '”',
	ldquo: '“',
};

function decodeEntities(text: string): string {
	return text.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, code: string) => {
		if (code[0] === '#') {
			const codePoint = code[1] === 'x' || code[1] === 'X' ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
			return Number.isNaN(codePoint) ? match : String.fromCodePoint(codePoint);
		}
		return code in ENTITIES ? ENTITIES[code] : match;
	});
}

/** Splits an HTML blurb into plain-text paragraphs, decoding entities and dropping every tag. */
export function htmlToParagraphs(html: string): string[] {
	const withBreaks = html.replace(/<br\s*\/?>/gi, '\n').replace(/<\/p>/gi, '\n\n');
	const stripped = withBreaks.replace(/<[^>]*>/g, '');
	const decoded = decodeEntities(stripped);
	return decoded
		.split(/\n+/)
		.map((p) => p.trim())
		.filter((p) => p.length > 0);
}
