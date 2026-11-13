from django.test import TestCase
from django.urls import reverse


class AppRoutesTests(TestCase):
    def test_home_and_app_pages_are_available(self):
        for route in ('core:home', 'academics:home'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)

    def test_optimizer_page_requires_staff_login(self):
        response = self.client.get(reverse('optimizer:home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin:login'), response['Location'])
