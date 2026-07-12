<div class="help">
	<h1 class="heading">Help.</h1>

	<div class="sections">
		<section>
			<h2 class="section-title small-caps">Library</h2>
			<p>
				Your private collection, arranged as a catalogue. Books in progress appear in the
				<em>Currently Reading</em> carousel at the top; your full Index of Series lies below.
				Hover a series row to expand its covers. Click a cover to inspect the volume.
			</p>
		</section>

		<section>
			<h2 class="section-title small-caps">Upload</h2>
			<p>
				Drop an EPUB onto the acquisition page. BookLens reads the title page and prefills the
				catalog entry; you may correct any field before shelving. The volume is indexed in the
				background — you need not wait.
			</p>
		</section>

		<section>
			<h2 class="section-title small-caps">Ask</h2>
			<p>
				Put a question to your library. Answers are drawn only from the chapters you have
				already read — the spoiler boundary is your bookmark, and it holds. Past inquiries
				are preserved in the left rail for the duration of your session.
			</p>
		</section>

		<section>
			<h2 class="section-title small-caps">Explore</h2>
			<p>
				The endpaper: a diagram of acquaintance for a series, drawn as of whichever chapter
				you set the scrubber to. Drag the brass tab to move through the story; the recap
				panel on the right follows. The graph is a work in progress.
			</p>
		</section>
	</div>
</div>

<style>
	.help {
		max-width: 640px;
	}
	.heading {
		font-family: var(--serif-display);
		font-style: italic;
		font-size: var(--fs-56);
		color: var(--bone);
		margin: 0 0 var(--sp-12);
		line-height: 1.1;
	}
	.sections {
		display: flex;
		flex-direction: column;
		gap: var(--sp-8);
	}
	section { border-top: var(--hairline); padding-top: var(--sp-6); }
	.section-title {
		color: var(--bone-muted);
		margin: 0 0 var(--sp-3);
	}
	p {
		font-family: var(--serif-body);
		font-style: italic;
		font-size: var(--fs-18);
		color: var(--bone-muted);
		line-height: 1.7;
		margin: 0;
	}
	em { color: var(--bone); font-style: italic; }
</style>
