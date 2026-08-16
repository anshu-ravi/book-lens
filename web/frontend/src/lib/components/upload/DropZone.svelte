<script lang="ts">
	let { onfile }: { onfile: (f: File) => void } = $props();

	let dragging = $state(false);

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		dragging = false;
		const file = e.dataTransfer?.files[0];
		if (file?.name.endsWith('.epub')) onfile(file);
	}

	function handleChange(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (file) onfile(file);
	}
</script>

<label
	class="drop-zone"
	class:dragging
	ondragover={(e) => {
		e.preventDefault();
		dragging = true;
	}}
	ondragleave={() => (dragging = false)}
	ondrop={handleDrop}
>
	<input type="file" accept=".epub" onchange={handleChange} style="display:none" />
	<span class="prompt">Drop a volume here, or browse to acquire.</span>
</label>

<style>
	.drop-zone {
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px dashed var(--ink-hairline);
		border-radius: var(--r-cover);
		min-height: 280px;
		cursor: pointer;
		transition: border-color 0.15s;
	}
	.drop-zone.dragging {
		border-color: var(--brass);
	}
	.prompt {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone-muted);
		text-align: center;
		padding: var(--sp-8);
	}
</style>
