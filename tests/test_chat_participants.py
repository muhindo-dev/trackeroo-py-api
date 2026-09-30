"""Chat participant authorization; no database connection is used."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from backend.routes.chat import chat_bp


class ChatParticipantTests(unittest.TestCase):
    def test_sender_cannot_address_third_party_through_existing_thread(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(chat_bp)
        head = SimpleNamespace(id=7, product_owner_id=2, customer_id=3)
        with patch('backend.utils.auth.get_current_user', return_value=SimpleNamespace(
            id=2, name='Driver'
        )), patch('backend.routes.chat.ChatHead') as chat_head, patch(
            'backend.routes.chat.AdminUser'
        ) as user_model:
            chat_head.query.get.return_value = head
            response = app.test_client().post('/api/chat-send', json={
                'chat_head_id': 7, 'receiver_id': 4, 'body': 'wrong recipient'
            })
            self.assertEqual(response.status_code, 403)
            user_model.query.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
