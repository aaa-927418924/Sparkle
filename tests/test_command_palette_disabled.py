import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CommandPaletteDisabledTests(unittest.TestCase):
    def test_command_palette_assets_are_not_loaded_by_pages(self):
        pages = (
            "index.html",
            "note-editor.html",
            "notes.html",
            "profile.html",
            "projects.html",
            "settings.html",
        )
        for page in pages:
            content = (ROOT / "frontend" / page).read_text(encoding="utf-8")
            self.assertNotIn("command-palette.js", content, page)
            self.assertNotIn("command-palette.css", content, page)

    def test_command_palette_api_and_preload_are_disabled(self):
        routers = (ROOT / "routers.py").read_text(encoding="utf-8")
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        shell = (ROOT / "frontend" / "codex-shell.js").read_text(encoding="utf-8")

        self.assertNotIn("@router.get(\"/command-palette/", routers)
        self.assertNotIn("@router.post(\"/command-palette/", routers)
        self.assertNotIn("preload_intent_parser", main)
        self.assertNotIn("preload_embedding_model", main)
        self.assertNotIn(".command-palette", shell)

    def test_lightweight_spec_has_no_local_llm_or_cuda_collection(self):
        spec = (ROOT / "Sparkle.spec").read_text(encoding="utf-8").casefold()
        requirements = (ROOT / "requirements-ai.txt").read_text(encoding="utf-8").casefold()

        for marker in ("torch", "transformers", "accelerate", "gguf", "nvidia"):
            self.assertNotIn(marker, spec, marker)
        self.assertNotIn("torch>=", requirements)
        self.assertNotIn("transformers>=", requirements)


if __name__ == "__main__":
    unittest.main()
