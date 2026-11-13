from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model


class AppRoutesTests(TestCase):
    def test_home_and_app_pages_are_available(self):
        for route in ('core:home', 'academics:home'):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)

    def test_optimizer_page_has_public_read_only_view(self):
        response = self.client.get(reverse('optimizer:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'عرض عام للنتيجة')

    def test_registration_login_and_logout_from_site(self):
        response = self.client.post(reverse('core:register'), {
            'username': 'newviewer', 'password1': 'StrongPass_8472!',
            'password2': 'StrongPass_8472!',
        })
        self.assertRedirects(response, reverse('optimizer:home'))
        user = get_user_model().objects.get(username='newviewer')
        self.assertFalse(user.is_staff)
        self.assertEqual(self.client.post(reverse('optimizer:home'), {'action': 'baseline'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('core:logout')), reverse('core:home'))
        response = self.client.post(reverse('core:login'), {
            'username': 'newviewer', 'password': 'StrongPass_8472!',
            'next': 'https://outside.example/',
        })
        self.assertRedirects(response, reverse('optimizer:home'))

    def test_invalid_registration_does_not_create_account(self):
        response = self.client.post(reverse('core:register'), {
            'username': 'newviewer', 'password1': 'short', 'password2': 'different',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='newviewer').exists())
