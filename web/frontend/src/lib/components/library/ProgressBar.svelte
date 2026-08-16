<script lang="ts">
	let { percent }: { percent: number } = $props();
</script>

<div class="track" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
	<div class="fill" style="width:{percent}%"></div>
</div>

<style>
	.track {
		width: 100%;
		height: 2px;
		background: var(--ink-hairline);
		border-radius: 1px;
		overflow: hidden;
	}
	.fill {
		height: 100%;
		background: var(--brass);
	}
</style>
