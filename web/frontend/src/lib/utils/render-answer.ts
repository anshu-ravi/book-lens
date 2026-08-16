import { marked } from 'marked';

function escapeHtml(raw: string): string {
	return raw
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

/** Render model markdown into safe HTML, turning known citation markers into clickable chips. */
export function renderAnswer(raw: string, citations: string[]): string {
	const escaped = escapeHtml(raw);
	const html = marked.parse(escaped, { async: false, breaks: true }) as string;

	let out = html;
	for (const id of citations) {
		const marker = `[${escapeHtml(id)}]`;
		out = out.split(marker).join(
			`<button type="button" class="citation-chip" data-citation-id="${escapeHtml(id)}">${citationNumber(citations, id)}</button>`,
		);
	}
	return out;
}

function citationNumber(citations: string[], id: string): number {
	return citations.indexOf(id) + 1;
}
