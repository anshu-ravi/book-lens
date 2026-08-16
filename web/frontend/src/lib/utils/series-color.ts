// Deterministic series ID -> cover background color.
const PALETTE = [
	'#1e3a5f', // slate-navy
	'#3d1f1f', // deep oxblood
	'#1a2e1a', // forest-green
	'#2e2410', // brass-dark
	'#1f1f3a', // deep indigo
	'#2a1f0e', // tawny
	'#0e2a2a', // deep teal
];

export function seriesColor(seriesId: string): string {
	let hash = 0;
	for (let i = 0; i < seriesId.length; i++) {
		hash = (hash * 31 + seriesId.charCodeAt(i)) >>> 0;
	}
	return PALETTE[hash % PALETTE.length];
}
