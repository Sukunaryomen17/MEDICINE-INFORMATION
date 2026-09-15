import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from MediData.services.classifier import classify_item
from MediData.services.medicine_matcher import find_medicine_details, search_medicines, get_medicine_by_name
from MediData.services.onemg import _clean_price
from MediData.forms import RegistrationForm, PDFUploadForm


class ServicesTestCase(TestCase):
    def test_classifier(self):
        self.assertEqual(classify_item("CBC Blood Test"), "LAB_TEST")
        self.assertEqual(classify_item("MRI BRAIN SCAN"), "LAB_TEST")
        self.assertEqual(classify_item("ICU BED CHARGES"), "HOSPITAL_SERVICE")
        self.assertEqual(classify_item("DOCTOR CONSULTATION"), "HOSPITAL_SERVICE")
        self.assertEqual(classify_item("CATHETER 16G"), "MEDICAL_DEVICE")
        self.assertEqual(classify_item("IV SET WITH NEEDLE"), "MEDICAL_DEVICE")
        self.assertEqual(classify_item("Augmentin 625 Duo Tablet"), "MEDICINE")
        self.assertEqual(classify_item("Dolo 650 Tablet"), "MEDICINE")

    def test_medicine_matcher(self):
        match = find_medicine_details("Augmentin 625")
        self.assertIsNotNone(match)
        self.assertIn("Augmentin", match["matched_name"])
        self.assertIn("Amoxycillin", match["composition"])

    def test_medicine_search(self):
        results = search_medicines("dolo", limit=5)
        self.assertTrue(len(results) > 0)
        self.assertTrue(any("Dolo" in r["name"] for r in results))

    def test_clean_price(self):
        self.assertEqual(_clean_price("₹150.50"), 150.50)
        self.assertEqual(_clean_price(200), 200.0)
        self.assertIsNone(_clean_price("invalid"))


class ViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123"
        )

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MediData")
        self.assertContains(response, "Understand your medical bills")

    def test_api_search_medicines(self):
        response = self.client.get("/api/medicines/search/?q=paracetamol")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("results"), list)

    def test_api_medicine_detail(self):
        response = self.client.get("/api/medicines/detail/?name=Augmentin+625+Duo+Tablet")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("medicine", data)

    def test_analyse_unauthenticated(self):
        sample_pdf = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        response = self.client.post("/analyse/", {"file": sample_pdf})
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn("Authentication required", data.get("error", ""))

    def test_login_and_register_pages(self):
        login_res = self.client.get("/login/")
        self.assertEqual(login_res.status_code, 200)
        reg_res = self.client.get("/register/")
        self.assertEqual(reg_res.status_code, 200)


class FormsTestCase(TestCase):
    def test_pdf_upload_form_validation(self):
        # Valid PDF
        valid_pdf = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 valid", content_type="application/pdf")
        form = PDFUploadForm({}, {"file": valid_pdf})
        self.assertTrue(form.is_valid())

        # Invalid file type
        invalid_exe = SimpleUploadedFile("malicious.exe", b"binary content", content_type="application/octet-stream")
        form_invalid = PDFUploadForm({}, {"file": invalid_exe})
        self.assertFalse(form_invalid.is_valid())

