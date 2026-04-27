# vigor-adapter-video-manim

Standalone VIGOR adapter for Manim scene generation.

This package does not require Manim in default CI. The adapter builds an executable Manim scene file and uses an injectable subprocess runner. Unit tests use a fake runner that creates the expected MP4 path. Real rendering requires `manim` on `PATH`.

Reference command:

```bash
manim --media_dir <run-media-dir> --format mp4 -ql --progress_bar none scene.py SceneName
```
