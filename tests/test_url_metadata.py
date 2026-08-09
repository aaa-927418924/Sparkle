import unittest
from unittest.mock import patch

from routers import (
    _collect_url_metadata,
    _enrich_url_clip_metadata,
    _extract_page_image,
    _extract_page_title,
    _youtube_thumbnail_url,
)


class UrlMetadataTests(unittest.TestCase):
    def test_open_graph_title_and_image_are_extracted(self):
        page = """
        <html><head>
          <meta property="og:title" content="Example title">
          <meta property="og:image" content="/images/preview.jpg">
        </head></html>
        """
        self.assertEqual(_extract_page_title(page), "Example title")
        self.assertEqual(_extract_page_image(page), "/images/preview.jpg")

    def test_page_metadata_resolves_relative_thumbnail_url(self):
        page = '<meta property="og:title" content="Example"><meta property="og:image" content="/preview.jpg">'
        with patch("routers._fetch_metadata_page", return_value=(page, "https://example.com/articles/1")):
            self.assertEqual(
                _collect_url_metadata("https://example.com/articles/1"),
                (
                    "https://example.com/articles/1",
                    "Example",
                    "https://example.com/preview.jpg",
                ),
            )

    def test_youtube_thumbnail_is_derived_without_an_api_key(self):
        self.assertEqual(
            _youtube_thumbnail_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        )
        self.assertEqual(
            _youtube_thumbnail_url("https://youtu.be/dQw4w9WgXcQ"),
            "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        )

    def test_clip_enrichment_fills_missing_title_and_thumbnail(self):
        with patch(
            "routers._collect_url_metadata",
            return_value=(
                "https://example.com/page",
                "Fetched title",
                "https://example.com/preview.jpg",
            ),
        ):
            self.assertEqual(
                _enrich_url_clip_metadata("https://example.com/page", None, None),
                ("Fetched title", "https://example.com/preview.jpg"),
            )

    def test_existing_clip_metadata_is_not_overwritten(self):
        with patch("routers._collect_url_metadata") as collect:
            self.assertEqual(
                _enrich_url_clip_metadata(
                    "https://example.com/page",
                    "Manual title",
                    "https://example.com/manual.jpg",
                ),
                ("Manual title", "https://example.com/manual.jpg"),
            )
        collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
