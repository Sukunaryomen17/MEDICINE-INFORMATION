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



class MedicineMatcherTestCase(TestCase):
    """
    Cover for the matching rewrite.

    The old WRatio matcher scored 15.2% exact on 400 perturbed real names and
    returned a *different molecule* 35.8% of the time -- every wrong answer at
    85.5, the value WRatio gives a broad class of partial matches, which is why
    a threshold of 80 admitted them. The rewrite scores 95.5% exact with no
    different-molecule answers. These tests pin the behaviours that got it
    there, so a future tweak cannot quietly reintroduce the old failure.
    """

    # Each of these was an observed wrong answer. The assertion is on the
    # molecule, not the brand: any product with the right molecule is fine.
    MOLECULE_CASES = [
        ("Crocin 500", "paracetamol", "was Azithral 500 (azithromycin)"),
        ("Pan 40", "pantoprazole", "was Atorva 40 (atorvastatin)"),
        ("Lasix 40", "furosemide", "was Atorva 40 (atorvastatin)"),
        ("Clopidogrel 75 mg tab", "clopidogrel", "was Augpen HS suspension"),
        ("Metformin 500", "metformin", "was Althrocin 500 (azithromycin)"),
        ("Diclofenac 50", "diclofenac", "was Arbitel-Trio 50"),
        ("Omeprazole 20", "omeprazole", "was Atorfit CV 20"),
        ("Ranitidine 150", "ranitidine", "was Afogatran 150"),
    ]

    def test_matches_resolve_to_the_right_molecule(self):
        for query, molecule, previously in self.MOLECULE_CASES:
            with self.subTest(query=query):
                result = find_medicine_details(query)
                self.assertIsNotNone(result, f"{query} should match ({previously})")
                self.assertIn(
                    molecule, result["composition"].lower(),
                    f"{query} -> {result['matched_name']} "
                    f"({result['composition']}); expected {molecule}. {previously}",
                )

    def test_strength_picks_the_right_pack(self):
        """Core 'augmentin' matches the injection; 625 must win the Duo tablet."""
        result = find_medicine_details("Augmentin 625")
        self.assertEqual(result["matched_name"], "Augmentin 625 Duo Tablet")

    def test_generic_name_resolves_via_composition(self):
        """Bills often name the molecule, not a brand."""
        result = find_medicine_details("TAB. PARACETAMOL 500MG")
        self.assertIsNotNone(result)
        self.assertIn("paracetamol", result["composition"].lower())

    def test_billing_lines_never_match(self):
        for line in ("GST 12%", "CGST 6%", "Round Off", "Advance Paid",
                     "Total Payable", "Discount", "ROOM RENT GENERAL WARD",
                     "NURSING CHARGES", "OT CHARGES"):
            with self.subTest(line=line):
                self.assertIsNone(find_medicine_details(line))

    def test_lab_and_device_lines_never_match(self):
        """Defence in depth: the classifier should catch these first."""
        for line in ("X-RAY CHEST PA VIEW", "CBC COMPLETE BLOOD COUNT",
                     "MRI BRAIN SCAN", "IV SET WITH NEEDLE", "SURGICAL GLOVES"):
            with self.subTest(line=line):
                self.assertIsNone(find_medicine_details(line))

    def test_unknown_brand_returns_nothing_rather_than_a_guess(self):
        self.assertIsNone(find_medicine_details("Zincovit"))
        self.assertIsNone(find_medicine_details("Nonexistentium 999"))

    def test_bill_formatting_is_normalised(self):
        """TAB./INJ. prefixes, pack counts and case must not change the answer."""
        baseline = find_medicine_details("Augmentin 625 Duo Tablet")
        self.assertIsNotNone(baseline)
        for variant in ("TAB. AUGMENTIN 625 DUO", "AUGMENTIN 625 DUO 10S",
                        "augmentin-625 duo tablet", "AuGmEnTiN 625 DuO TaBlEt",
                        "AUGMENTIN 625 DUO TABLET 1X10"):
            with self.subTest(variant=variant):
                self.assertEqual(
                    find_medicine_details(variant)["matched_name"],
                    baseline["matched_name"],
                )

    def test_empty_and_junk_input(self):
        for value in ("", None, "   ", "%%%", "12345"):
            with self.subTest(value=value):
                self.assertIsNone(find_medicine_details(value))

    def test_result_shape_is_unchanged(self):
        """views.py and the frontend read these keys."""
        result = find_medicine_details("Pan 40")
        self.assertEqual(
            set(result),
            {"matched_name", "composition", "uses", "side_effects",
             "manufacturer", "image_url", "match_score"},
        )
        self.assertIsInstance(result["match_score"], float)

    def test_search_and_lookup_api_still_work(self):
        results = search_medicines("augmentin", limit=5)
        self.assertTrue(results)
        self.assertTrue(any("Augmentin" in r["name"] for r in results))
        self.assertIsNotNone(get_medicine_by_name("Augmentin 625 Duo Tablet"))


class MatcherNormalisationTestCase(TestCase):
    """Unit cover for the parsing the matcher is built on."""

    def test_brand_core_drops_form_and_strength(self):
        from MediData.services.medicine_matcher import split_name
        self.assertEqual(split_name("TAB. DOLO 650")[0], "dolo")
        self.assertEqual(split_name("Azithral 500 Tablet")[0], "azithral")
        self.assertEqual(split_name("INJ. MONOCEF 1GM")[0], "monocef")

    def test_brand_core_keeps_distinguishing_words(self):
        """SR/CV/Forte are part of the product identity, not packaging."""
        from MediData.services.medicine_matcher import split_name
        self.assertEqual(split_name("PROVANOL SR 40 1X10")[0], "provanol sr")
        self.assertEqual(split_name("Crocin Advance 500mg Tablet")[0], "crocin advance")

    def test_strengths_are_extracted(self):
        from MediData.services.medicine_matcher import split_name
        self.assertEqual(split_name("Pan 40 Tablet")[1], frozenset({40.0}))
        self.assertEqual(split_name("GTN Sorbitrate CR 2.6 Tablet")[1], frozenset({2.6}))

    def test_billing_line_detection(self):
        from MediData.services.medicine_matcher import looks_like_billing_line, split_name
        self.assertTrue(looks_like_billing_line(split_name("Total Payable")[0]))
        self.assertTrue(looks_like_billing_line(split_name("ROOM RENT")[0]))
        self.assertFalse(looks_like_billing_line(split_name("Crocin 500")[0]))
