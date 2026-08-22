/** Shared SVG path builders and formatting helpers for the stats charts. */

/** Horizontal bar: rounded at the right (data) end, square at the left (baseline). */
export function hBarPath(x: number, y: number, width: number, height: number, radius = 4): string {
	if (width <= 0 || height <= 0) return '';
	const r = Math.min(radius, width, height / 2);
	if (r <= 0.01) {
		return `M ${x},${y} h ${width} v ${height} h ${-width} Z`;
	}
	return `M ${x},${y} H ${x + width - r} Q ${x + width},${y} ${x + width},${y + r} V ${y + height - r} Q ${x + width},${y + height} ${x + width - r},${y + height} H ${x} Z`;
}

/** Vertical column: rounded at the top (data) end, square at the baseline. */
export function vBarPath(x: number, y: number, width: number, height: number, radius = 4): string {
	if (width <= 0 || height <= 0) return '';
	const r = Math.min(radius, height, width / 2);
	if (r <= 0.01) {
		return `M ${x},${y + height} v ${-height} h ${width} v ${height} Z`;
	}
	return `M ${x},${y + height} V ${y + r} Q ${x},${y} ${x + r},${y} H ${x + width - r} Q ${x + width},${y} ${x + width},${y + r} V ${y + height} Z`;
}

export const MONTH_ABBR = [
	'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

export const MONTH_FULL = [
	'January', 'February', 'March', 'April', 'May', 'June',
	'July', 'August', 'September', 'October', 'November', 'December',
];

export function monthIndex(key: string): number {
	return Number(key.split('-')[1]) - 1;
}

export function monthYear(key: string): number {
	return Number(key.split('-')[0]);
}

export function monthFullLabel(key: string): string {
	return `${MONTH_FULL[monthIndex(key)]} ${monthYear(key)}`;
}

export function ellipsize(s: string, max: number): string {
	return s.length > max ? s.slice(0, max - 1) + '…' : s;
}
