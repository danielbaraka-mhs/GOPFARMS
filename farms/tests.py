from django.test import SimpleTestCase
from django.urls import reverse


class PageTests(SimpleTestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GOP FARMS")

    def test_categories_page_loads(self):
        response = self.client.get(reverse("categories"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Categories")
