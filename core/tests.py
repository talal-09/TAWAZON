from django.test import TestCase
from django.urls import reverse


class AppRoutesTests(TestCase):
    def test_home_and_app_pages_are_available(self):
        for route in ('core:home', 'academics:home', 'optimizer:home'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
