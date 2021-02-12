import uuid
from datetime import datetime, timedelta

import pytest
from asynctest import patch
from google.oauth2 import service_account
from pytest_httpx import HTTPXMock

from async_firebase.client import AsyncFirebaseClient


pytestmark = pytest.mark.asyncio


@pytest.fixture()
def fake_async_fcm_client():
    return AsyncFirebaseClient()


@pytest.fixture()
def fake_async_fcm_client_w_creds(fake_async_fcm_client, fake_service_account):
    client = AsyncFirebaseClient()
    client.creds_from_service_account_info(fake_service_account)
    return client


def fake_jwt_grant():
    return "fake-jwt-token", datetime.utcnow() + timedelta(days=30), {}


def fake_google_refresh(self, request):
    if self._jwt_credentials is not None:
        self._jwt_credentials.refresh(request)
        self.token = self._jwt_credentials.token
        self.expiry = self._jwt_credentials.expiry
    else:
        access_token, expiry, _ = fake_jwt_grant()
        self.token = access_token
        self.expiry = expiry


class TestAsyncFirebaseClient:

    async def test__get_access_token(self, fake_async_fcm_client_w_creds):
        with patch("google.oauth2.service_account.Credentials.refresh", fake_google_refresh):
            access_token = await fake_async_fcm_client_w_creds._get_access_token()
            assert access_token == "fake-jwt-token"

    async def test__get_access_token_called_once(self, fake_async_fcm_client_w_creds):
        with patch("google.oauth2._client.jwt_grant", return_value=fake_jwt_grant()) as mocked_refresh:
            for _ in range(3):
                await fake_async_fcm_client_w_creds._get_access_token()

            # since the token still valid, there should be only one request to fetch token
            assert mocked_refresh.call_count == 1

    def test_build_common_message(self, fake_async_fcm_client_w_creds, freezer):
        frozen_uuid = uuid.UUID(hex='6eadf1d38633427cb83dbb9be137f48c')
        with patch.object(uuid, "uuid4", side_effect=[frozen_uuid]):
            common_message = fake_async_fcm_client_w_creds.build_common_message()
            assert common_message == {
                "message": {
                    "android": {},
                    "apns": {},
                    "condition": None,
                    "data": {
                        "push_id": str(frozen_uuid),
                        "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                    "notification": {},
                    "token": None,
                    "topic": None,
                    "webpush": None,
                }
            }

    def test_build_android_message(self, fake_async_fcm_client_w_creds):
        android_message, _ = fake_async_fcm_client_w_creds.build_android_message(
            priority="high",
            ttl=7200,
            collapse_key="something",
            restricted_package_name="some-package",
            data={"key_1": "value_1", "key_2": 100},
            color="red",
            sound="beep",
            tag="test",
            click_action="TOP_STORY_ACTIVITY"
        )
        assert android_message == {
            "priority": "high",
            "collapse_key": "something",
            "restricted_package_name": "some-package",
            "data": {"key_1": "value_1", "key_2": "100"},
            "ttl": "7200s",
            "notification": {
                "color": "red",
                "sound": "beep",
                "tag": "test",
                "click_action": "TOP_STORY_ACTIVITY"
            }
        }

    def test_build_apns_message(self, fake_async_fcm_client_w_creds, freezer):
        apns_message, _ = fake_async_fcm_client_w_creds.build_apns_message(
            priority="high",
            ttl=7200,
            apns_topic="test-topic",
            collapse_key="something",
            alert="alert-message",
            badge=0,
        )
        assert apns_message == {
            "headers": {
                "apns-expiration": str(int(datetime.utcnow().timestamp()) + 7200),
                "apns-priority": "10",
                "apns-topic": "test-topic",
                "apns-collapse-id": "something",
            },
            "payload": {
                "aps": {
                    "alert": "alert-message",
                    "badge": 0,
                    "sound": "default",
                    "content_available": True,
                    "category": None,
                    "thread_id": None,
                    "mutable_content": True,
                    "custom_data": None,
                }
            }
        }

    async def test__prepare_headers(self, fake_async_fcm_client_w_creds):
        with patch("google.oauth2.service_account.Credentials.refresh", fake_google_refresh):
            headers = await fake_async_fcm_client_w_creds._prepare_headers()
            assert headers == {
                "Authorization": "Bearer fake-jwt-token",
                "Content-Type": "application/json; UTF-8",
            }

    async def test_push(self, fake_async_fcm_client_w_creds, faker_, httpx_mock: HTTPXMock):
        device_token = faker_.bothify(text=f"{'?' * 12}:{'?' * 256}")
        creds = fake_async_fcm_client_w_creds._credentials
        httpx_mock.add_response(
            status_code=200,
            json={'name': f'projects/{creds.project_id}/messages/0:1612788010922733%7606eb247606eb24'}
        )
        with patch("google.oauth2.service_account.Credentials.refresh", fake_google_refresh):
            response = await fake_async_fcm_client_w_creds.push(
                device_token=device_token,
                notification_title="Test Title",
                notification_body="Test body",
                notification_data={"foo": "bar"},
                priority="normal",
                apns_topic="test-push",
                collapse_key="push",
                alert_text="test-alert",
                category="test-category",
                badge=0,
            )
        assert response == {'name': 'projects/fake-mobile-app/messages/0:1612788010922733%7606eb247606eb24'}

    async def test_push_dry_run(self, fake_async_fcm_client_w_creds, faker_, httpx_mock: HTTPXMock):
        device_token = faker_.bothify(text=f"{'?' * 12}:{'?' * 256}")
        creds = fake_async_fcm_client_w_creds._credentials
        httpx_mock.add_response(
            status_code=200,
            json={'name': f'projects/{creds.project_id}/messages/fake_message_id'}
        )
        with patch("google.oauth2.service_account.Credentials.refresh", fake_google_refresh):
            response = await fake_async_fcm_client_w_creds.push(
                device_token=device_token,
                notification_title="Test Title",
                notification_body="Test body",
                notification_data={"foo": "bar"},
                priority="normal",
                apns_topic="test-push",
                collapse_key="push",
                alert_text="test-alert",
                category="test-category",
                badge=0,
                dry_run=True
            )
        assert response == {'name': 'projects/fake-mobile-app/messages/fake_message_id'}

    async def test_push_unauthenticated(self, fake_async_fcm_client_w_creds, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            status_code=401,
            json={
                'error': {
                    'code': 401,
                    'message': 'Request had invalid authentication credentials. '
                               'Expected OAuth 2 access token, login cookie or other '
                               'valid authentication credential. See '
                               'https://developers.google.com/identity/sign-in/web/devconsole-project.',
                    'status': 'UNAUTHENTICATED'
                }
            }
        )
        with patch("google.oauth2.service_account.Credentials.refresh", fake_google_refresh):
            response = await fake_async_fcm_client_w_creds.push(
                device_token="qwerty:ytrewq",
                notification_title="Test Title",
                notification_body="Test body",
                notification_data={"foo": "bar"},
                priority="normal",
                apns_topic="test-push",
                collapse_key="push",
                alert_text="test-alert",
                category="test-category",
                badge=0,
            )
            assert response["error"]["code"] == 401

    def test_creds_from_service_account_info(self, fake_async_fcm_client, fake_service_account):
        fake_async_fcm_client.creds_from_service_account_info(fake_service_account)
        assert isinstance(fake_async_fcm_client._credentials, service_account.Credentials)

    def test_creds_from_service_account_file(self, fake_async_fcm_client, fake_service_account_file):
        fake_async_fcm_client.creds_from_service_account_file(fake_service_account_file)
        assert isinstance(fake_async_fcm_client._credentials, service_account.Credentials)