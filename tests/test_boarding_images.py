"""Real Pillow/filesystem checks and mocked-database cover route tests."""

from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mysql.connector import Error
from PIL import Image
from werkzeug.datastructures import FileStorage

from app import app
from boarding_images import (
    InvalidCoverImage, MAX_COVER_BYTES, cover_image_path, remove_cover_image, save_cover_image,
)
import test_boarding_profile as profile_tests


def photo_bytes(format="PNG", size=(80, 40), **options):
    stream = BytesIO()
    with Image.new("RGB", size, "#138ca5") as image:
        image.save(stream, format=format, **options)
    return stream.getvalue()


def upload(data, filename="cover.png"):
    return FileStorage(stream=BytesIO(data), filename=filename, name="cover_photo")


class CoverImageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "covers"
        self.root.mkdir()
        override = patch.dict(app.config, {"BOARDING_UPLOAD_ROOT": str(self.root)})
        override.start()
        self.addCleanup(override.stop)
        context = app.app_context()
        context.push()
        self.addCleanup(context.pop)

    def test_no_photo_is_optional(self):
        self.assertIsNone(save_cover_image(None))
        self.assertIsNone(save_cover_image(upload(b"", "")))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_jpeg_png_webp_are_decoded_and_normalized(self):
        for format in ("JPEG", "PNG", "WEBP"):
            with self.subTest(format=format):
                filename = save_cover_image(upload(photo_bytes(format=format), "untrusted.exe"))
                self.assertRegex(filename, r"^[a-f0-9]{32}\.webp$")
                with Image.open(cover_image_path(filename)) as saved:
                    self.assertEqual(saved.format, "WEBP")
                    self.assertEqual(saved.size, (80, 40))

    def test_portrait_landscape_and_square_fit_without_upscaling(self):
        for size, expected in (((40, 80), (40, 80)), ((3000, 1000), (1920, 640)), ((2000, 2000), (1920, 1920))):
            with self.subTest(size=size):
                filename = save_cover_image(upload(photo_bytes(size=size)))
                with Image.open(cover_image_path(filename)) as saved:
                    self.assertEqual(saved.size, expected)

    def test_exif_orientation_is_applied_and_metadata_removed(self):
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "private test metadata"
        filename = save_cover_image(upload(photo_bytes(format="JPEG", exif=exif)))
        with Image.open(cover_image_path(filename)) as saved:
            self.assertEqual(saved.size, (40, 80))
            self.assertFalse(saved.getexif())

    def test_transparent_png_is_normalized(self):
        stream = BytesIO()
        with Image.new("RGBA", (10, 10), (10, 20, 30, 0)) as image:
            image.save(stream, format="PNG")
        filename = save_cover_image(upload(stream.getvalue()))
        with Image.open(cover_image_path(filename)) as saved:
            self.assertEqual(saved.mode, "RGB")

    def test_invalid_disguised_and_truncated_files_are_rejected(self):
        for data in (b"", b"not an image", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', photo_bytes(format="JPEG")[:100]):
            with self.subTest(length=len(data)), self.assertRaises(InvalidCoverImage):
                save_cover_image(upload(data))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_file_size_limit_is_checked_before_decoding(self):
        with self.assertRaisesRegex(InvalidCoverImage, "5 MB"):
            save_cover_image(upload(b"x" * (MAX_COVER_BYTES + 1)))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_dimension_limit_is_checked_before_decoding_pixels(self):
        with self.assertRaisesRegex(InvalidCoverImage, "6,000"):
            save_cover_image(upload(photo_bytes(size=(6001, 1))))

    def test_pixel_limit_is_enforced(self):
        with self.assertRaisesRegex(InvalidCoverImage, "20 megapixels"):
            save_cover_image(upload(photo_bytes(size=(5000, 4001))))

    def test_decompression_bomb_is_rejected(self):
        data = photo_bytes(size=(10, 10))
        with patch("boarding_images.Image.MAX_IMAGE_PIXELS", 10), self.assertRaises(InvalidCoverImage):
            save_cover_image(upload(data))

    def test_animation_is_rejected(self):
        stream = BytesIO()
        first = Image.new("RGB", (10, 10), "red")
        second = Image.new("RGB", (10, 10), "blue")
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.save(stream, format="WEBP", save_all=True, append_images=[second], duration=100, loop=0)
        with self.assertRaisesRegex(InvalidCoverImage, "still photo"):
            save_cover_image(upload(stream.getvalue()))

    def test_filename_traversal_cannot_read_or_remove_outside_file(self):
        outside = self.root.parent / "keep.webp"
        outside.write_bytes(b"keep")
        for name in ("../keep.webp", str(outside), "bad.webp", None):
            self.assertIsNone(cover_image_path(name))
            remove_cover_image(name)
        self.assertTrue(outside.exists())

    def test_partial_file_is_cleaned_if_storage_fails(self):
        data = photo_bytes()
        with patch("boarding_images.os.replace", side_effect=OSError("test storage error")), self.assertRaises(OSError):
            save_cover_image(upload(data))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cleanup_failure_is_logged_without_leaking_path(self):
        filename = save_cover_image(upload(photo_bytes()))
        with patch("boarding_images.Path.unlink", side_effect=OSError("private path")), self.assertLogs(app.logger, level="WARNING") as logs:
            remove_cover_image(filename)
        self.assertNotIn("private path", str(logs.output))


class CoverRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile_tests.BoardingProfileTests.setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = profile_tests.BoardingProfileTests("test_empty_state")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        override = patch.dict(app.config, {"BOARDING_UPLOAD_ROOT": str(self.root)})
        override.start()
        self.addCleanup(override.stop)
        self.client = self.fixture.client

    def existing_cover(self):
        with app.app_context():
            filename = save_cover_image(upload(photo_bytes()))
        self.fixture.boarding["cover_image_filename"] = filename
        return filename

    def test_create_with_photo_stores_generated_reference(self):
        data = self.fixture.create_payload()
        data["cover_photo"] = (BytesIO(photo_bytes()), "../../browser-name.png")
        response = self.client.post("/owner/boarding/create", data=data)
        self.assertEqual(response.status_code, 303)
        query, parameters = self.fixture.insert_calls()[0].args
        self.assertIn("cover_image_filename", query)
        self.assertTrue((self.root / parameters[-1]).is_file())
        self.assertNotIn("browser-name", parameters[-1])
        self.fixture.boarding_connection.commit.assert_called_once()

    def test_invalid_create_photo_preserves_fields_without_insert(self):
        data = self.fixture.create_payload()
        data["cover_photo"] = (BytesIO(b"invalid"), "fake.png")
        response = self.client.post("/owner/boarding/create", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn('id="cover_photo-error"', response.text)
        self.assertIn('value="Campus Boarding"', response.text)
        self.assertEqual(self.fixture.insert_calls(), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_create_cleans_new_photo(self):
        data = self.fixture.create_payload()
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        def execute(query, parameters):
            if query.lstrip().startswith("INSERT"):
                raise Error("test database failure", errno=1142)
        self.fixture.boarding_cursor.execute.side_effect = execute
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/create", data=data)
        self.assertEqual(response.status_code, 500)
        self.fixture.boarding_connection.rollback.assert_called_once()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_duplicate_create_cleans_new_photo_and_keeps_existing_profile(self):
        data = self.fixture.create_payload()
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        def execute(query, parameters):
            if query.lstrip().startswith("INSERT"):
                raise Error("test duplicate", errno=1062)
        self.fixture.boarding_cursor.execute.side_effect = execute
        self.assertEqual(self.client.post("/owner/boarding/create", data=data).status_code, 303)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_edit_no_replacement_keeps_current_cover(self):
        old = self.existing_cover()
        response = self.client.post("/owner/boarding/edit", data=self.fixture.edit_payload())
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("cover_image_filename", self.fixture.update_calls()[0].args[0])
        self.assertTrue((self.root / old).exists())
        self.assertIn('src="/owner/boarding/cover"', self.client.get("/owner/boarding").text)
        self.assertIn("Current boarding cover photo", self.client.get("/owner/boarding/edit").text)

    def test_wrong_password_never_processes_photo_or_changes_old_file(self):
        old = self.existing_cover()
        data = self.fixture.edit_payload(current_password="wrong")
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        with patch("owner_boarding.save_cover_image") as save:
            response = self.client.post("/owner/boarding/edit", data=data)
        self.assertEqual(response.status_code, 400)
        save.assert_not_called()
        self.assertTrue((self.root / old).exists())
        self.assertEqual(self.fixture.update_calls(), [])

    def test_invalid_replacement_preserves_current_cover(self):
        old = self.existing_cover()
        data = self.fixture.edit_payload()
        data["cover_photo"] = (BytesIO(b"invalid"), "photo.png")
        response = self.client.post("/owner/boarding/edit", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Current boarding cover photo", response.text)
        self.assertTrue((self.root / old).exists())
        self.assertEqual(self.fixture.update_calls(), [])

    def test_successful_replacement_removes_old_only_after_commit(self):
        old = self.existing_cover()
        data = self.fixture.edit_payload()
        data["cover_photo"] = (BytesIO(photo_bytes(size=(40, 80))), "photo.png")
        self.fixture.boarding_connection.commit.side_effect = lambda: self.assertTrue((self.root / old).exists())
        response = self.client.post("/owner/boarding/edit", data=data)
        self.assertEqual(response.status_code, 303)
        query, parameters = self.fixture.update_calls()[0].args
        self.assertIn("cover_image_filename = %s", query)
        self.assertTrue((self.root / parameters[-3]).exists())
        self.assertFalse((self.root / old).exists())

    def test_failed_replacement_cleans_new_and_keeps_old(self):
        old = self.existing_cover()
        data = self.fixture.edit_payload()
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        def execute(query, parameters):
            if query.lstrip().startswith("UPDATE"):
                raise Error("test update failure", errno=1142)
        self.fixture.boarding_cursor.execute.side_effect = execute
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/edit", data=data)
        self.assertEqual(response.status_code, 500)
        self.assertEqual([path.name for path in self.root.iterdir()], [old])
        self.fixture.boarding_connection.rollback.assert_called_once()

    def test_replacement_uses_cover_from_locked_row_for_cleanup(self):
        first = self.existing_cover()
        with app.app_context():
            concurrent = save_cover_image(upload(photo_bytes()))
        data = self.fixture.edit_payload()
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        def fetchone():
            boarding = dict(self.fixture.boarding)
            if "FOR UPDATE" in self.fixture.boarding_cursor.execute.call_args.args[0]:
                boarding["cover_image_filename"] = concurrent
            return boarding
        self.fixture.boarding_cursor.fetchone.side_effect = fetchone
        response = self.client.post("/owner/boarding/edit", data=data)
        self.assertEqual(response.status_code, 303)
        self.assertFalse((self.root / concurrent).exists())
        self.assertTrue((self.root / first).exists())

    def test_private_cover_serves_normalized_image(self):
        self.existing_cover()
        response = self.client.get("/owner/boarding/cover")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/webp")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with Image.open(BytesIO(response.data)) as image:
            self.assertEqual(image.format, "WEBP")

    def test_guest_and_student_cannot_fetch_cover(self):
        self.existing_cover()
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/owner/boarding/cover").status_code, 302)
        self.fixture.sign_in()
        self.fixture.owner["role"] = "student"
        self.assertEqual(self.client.get("/owner/boarding/cover").status_code, 403)

    def test_owner_b_cannot_request_owner_a_cover_by_id_or_filename(self):
        old = self.existing_cover()
        self.fixture.owner["user_id"] = 99
        self.fixture.sign_in(user_id=99)
        self.fixture.boarding = None
        response = self.client.get("/owner/boarding/cover?owner_id=41&filename=" + old)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.fixture.boarding_cursor.execute.call_args.args[1], (99,))

    def test_missing_or_untrusted_stored_filename_returns_404(self):
        for filename in (None, "../../secret", "a" * 32 + ".webp"):
            self.fixture.boarding["cover_image_filename"] = filename
            self.assertEqual(self.client.get("/owner/boarding/cover").status_code, 404)

    def test_oversized_request_is_bounded_before_database_access(self):
        self.fixture.create_payload()
        response = self.client.post(
            "/owner/boarding/create", data=b"", content_type="multipart/form-data; boundary=test",
            environ_overrides={"CONTENT_LENGTH": str(MAX_COVER_BYTES + 1024 * 1024 + 1)},
        )
        self.assertEqual(response.status_code, 413)
        self.fixture.account_db.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_uncertain_commit_keeps_both_images_to_avoid_broken_reference(self):
        old = self.existing_cover()
        data = self.fixture.edit_payload()
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        self.fixture.boarding_connection.commit.side_effect = Error("test connection lost", errno=2013)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/edit", data=data)
        self.assertEqual(response.status_code, 500)
        self.assertTrue((self.root / old).exists())
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_photo_upload_still_requires_csrf(self):
        data = self.fixture.create_payload()
        data.pop("csrf_token")
        data["cover_photo"] = (BytesIO(photo_bytes()), "photo.png")
        self.assertEqual(self.client.post("/owner/boarding/create", data=data).status_code, 400)
        self.fixture.boarding_db.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
