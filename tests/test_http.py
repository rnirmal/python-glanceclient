# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import errno
import socket

import mock
from mox3 import mox
import six
from six.moves import http_client
from six.moves.urllib import parse
import tempfile
import testtools

import glanceclient
from glanceclient.common import http
from glanceclient.common import utils as client_utils
from glanceclient import exc
from tests import utils


class TestClient(testtools.TestCase):

    def setUp(self):
        super(TestClient, self).setUp()
        self.mock = mox.Mox()
        self.mock.StubOutWithMock(http_client.HTTPConnection, 'request')
        self.mock.StubOutWithMock(http_client.HTTPConnection, 'getresponse')

        self.endpoint = 'http://example.com:9292'
        self.client = http.HTTPClient(self.endpoint, token=u'abc123')

    def tearDown(self):
        super(TestClient, self).tearDown()
        self.mock.UnsetStubs()

    def test_identity_headers_and_token(self):
        identity_headers = {
            'X-Auth-Token': 'auth_token',
            'X-User-Id': 'user',
            'X-Tenant-Id': 'tenant',
            'X-Roles': 'roles',
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': 'service_catalog',
        }
        #with token
        kwargs = {'token': u'fake-token',
                  'identity_headers': identity_headers}
        http_client_object = http.HTTPClient(self.endpoint, **kwargs)
        self.assertEqual(http_client_object.auth_token, 'auth_token')
        self.assertTrue(http_client_object.identity_headers.
                        get('X-Auth-Token') is None)

    def test_identity_headers_and_no_token_in_header(self):
        identity_headers = {
            'X-User-Id': 'user',
            'X-Tenant-Id': 'tenant',
            'X-Roles': 'roles',
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': 'service_catalog',
        }
        #without X-Auth-Token in identity headers
        kwargs = {'token': u'fake-token',
                  'identity_headers': identity_headers}
        http_client_object = http.HTTPClient(self.endpoint, **kwargs)
        self.assertEqual(http_client_object.auth_token, u'fake-token')
        self.assertTrue(http_client_object.identity_headers.
                        get('X-Auth-Token') is None)

    def test_connection_refused(self):
        """
        Should receive a CommunicationError if connection refused.
        And the error should list the host and port that refused the
        connection
        """
        http_client.HTTPConnection.request(
            mox.IgnoreArg(),
            mox.IgnoreArg(),
            headers=mox.IgnoreArg(),
        ).AndRaise(socket.error())
        self.mock.ReplayAll()
        try:
            self.client.json_request('GET', '/v1/images/detail?limit=20')
            #NOTE(alaski) We expect exc.CommunicationError to be raised
            # so we should never reach this point.  try/except is used here
            # rather than assertRaises() so that we can check the body of
            # the exception.
            self.fail('An exception should have bypassed this line.')
        except glanceclient.exc.CommunicationError as comm_err:
            fail_msg = ("Exception message '%s' should contain '%s'" %
                       (comm_err.message, self.endpoint))
            self.assertTrue(self.endpoint in comm_err.message, fail_msg)

    def test_request_redirected(self):
        resp = utils.FakeResponse({'location': 'http://www.example.com'},
                                  status=302, body=six.StringIO())
        http_client.HTTPConnection.request(
            mox.IgnoreArg(),
            mox.IgnoreArg(),
            headers=mox.IgnoreArg(),
        )
        http_client.HTTPConnection.getresponse().AndReturn(resp)

        # The second request should be to the redirected location
        expected_response = 'Ok'
        resp2 = utils.FakeResponse({}, six.StringIO(expected_response))
        http_client.HTTPConnection.request(
            'GET',
            'http://www.example.com',
            headers=mox.IgnoreArg(),
        )
        http_client.HTTPConnection.getresponse().AndReturn(resp2)

        self.mock.ReplayAll()

        self.client.json_request('GET', '/v1/images/detail')

    def test_http_encoding(self):
        http_client.HTTPConnection.request(
            mox.IgnoreArg(),
            mox.IgnoreArg(),
            headers=mox.IgnoreArg())

        # Lets fake the response
        # returned by httplib
        expected_response = 'Ok'
        fake = utils.FakeResponse({}, six.StringIO(expected_response))
        http_client.HTTPConnection.getresponse().AndReturn(fake)
        self.mock.ReplayAll()

        headers = {"test": u'ni\xf1o'}
        resp, body = self.client.raw_request('GET', '/v1/images/detail',
                                                    headers=headers)
        self.assertEqual(resp, fake)

    def test_headers_encoding(self):
        headers = {"test": u'ni\xf1o'}
        encoded = self.client.encode_headers(headers)
        self.assertEqual(encoded["test"], "ni\xc3\xb1o")

    def test_raw_request(self):
        " Verify the path being used for HTTP requests reflects accurately. "

        def check_request(method, path, **kwargs):
            self.assertEqual(method, 'GET')
            # NOTE(kmcdonald): See bug #1179984 for more details.
            self.assertEqual(path, '/v1/images/detail')

        http_client.HTTPConnection.request(
            mox.IgnoreArg(),
            mox.IgnoreArg(),
            headers=mox.IgnoreArg()).WithSideEffects(check_request)

        # fake the response returned by httplib
        fake = utils.FakeResponse({}, six.StringIO('Ok'))
        http_client.HTTPConnection.getresponse().AndReturn(fake)
        self.mock.ReplayAll()

        resp, body = self.client.raw_request('GET', '/v1/images/detail')
        self.assertEqual(resp, fake)

    def test_customized_path_raw_request(self):
        """
        Verify the customized path being used for HTTP requests
        reflects accurately
        """

        def check_request(method, path, **kwargs):
            self.assertEqual(method, 'GET')
            self.assertEqual(path, '/customized-path/v1/images/detail')

        # NOTE(yuyangbj): see bug 1230032 to get more info
        endpoint = 'http://example.com:9292/customized-path'
        client = http.HTTPClient(endpoint, token=u'abc123')
        self.assertEqual(client.endpoint_path, '/customized-path')

        http_client.HTTPConnection.request(
            mox.IgnoreArg(),
            mox.IgnoreArg(),
            headers=mox.IgnoreArg()).WithSideEffects(check_request)

        # fake the response returned by httplib
        fake = utils.FakeResponse({}, six.StringIO('Ok'))
        http_client.HTTPConnection.getresponse().AndReturn(fake)
        self.mock.ReplayAll()

        resp, body = client.raw_request('GET', '/v1/images/detail')
        self.assertEqual(resp, fake)

    def test_raw_request_no_content_length(self):
        with tempfile.NamedTemporaryFile() as test_file:
            test_file.write(b'abcd')
            test_file.seek(0)
            data_length = 4
            self.assertEqual(client_utils.get_file_size(test_file),
                             data_length)

            exp_resp = {'body': test_file}
            exp_resp['headers'] = {'Content-Length': str(data_length),
                                   'Content-Type': 'application/octet-stream'}

            def mock_request(url, method, **kwargs):
                return kwargs

            rq_kwargs = {'body': test_file, 'content_length': None}

            with mock.patch.object(self.client, '_http_request') as mock_rq:
                mock_rq.side_effect = mock_request
                resp = self.client.raw_request('PUT', '/v1/images/detail',
                                               **rq_kwargs)

                rq_kwargs.pop('content_length')
                headers = {'Content-Length': str(data_length),
                           'Content-Type': 'application/octet-stream'}
                rq_kwargs['headers'] = headers

                mock_rq.assert_called_once_with('/v1/images/detail', 'PUT',
                                                **rq_kwargs)

            self.assertEqual(exp_resp, resp)

    def test_raw_request_w_content_length(self):
        with tempfile.NamedTemporaryFile() as test_file:
            test_file.write(b'abcd')
            test_file.seek(0)
            data_length = 4
            self.assertEqual(client_utils.get_file_size(test_file),
                             data_length)

            exp_resp = {'body': test_file}
            # NOTE: we expect the actual file size to be overridden by the
            # supplied content length.
            exp_resp['headers'] = {'Content-Length': '4',
                                   'Content-Type': 'application/octet-stream'}

            def mock_request(url, method, **kwargs):
                return kwargs

            rq_kwargs = {'body': test_file, 'content_length': data_length}

            with mock.patch.object(self.client, '_http_request') as mock_rq:
                mock_rq.side_effect = mock_request
                resp = self.client.raw_request('PUT', '/v1/images/detail',
                                               **rq_kwargs)

                rq_kwargs.pop('content_length')
                headers = {'Content-Length': str(data_length),
                           'Content-Type': 'application/octet-stream'}
                rq_kwargs['headers'] = headers

                mock_rq.assert_called_once_with('/v1/images/detail', 'PUT',
                                                **rq_kwargs)

            self.assertEqual(exp_resp, resp)

    def test_raw_request_w_bad_content_length(self):
        with tempfile.NamedTemporaryFile() as test_file:
            test_file.write(b'abcd')
            test_file.seek(0)
            self.assertEqual(client_utils.get_file_size(test_file), 4)

            def mock_request(url, method, **kwargs):
                return kwargs

            with mock.patch.object(self.client, '_http_request', mock_request):
                self.assertRaises(AttributeError, self.client.raw_request,
                                  'PUT', '/v1/images/detail', body=test_file,
                                  content_length=32)

    def test_connection_refused_raw_request(self):
        """
        Should receive a CommunicationError if connection refused.
        And the error should list the host and port that refused the
        connection
        """
        endpoint = 'http://example.com:9292'
        client = http.HTTPClient(endpoint, token=u'abc123')
        http_client.HTTPConnection.request(mox.IgnoreArg(), mox.IgnoreArg(),
                                           headers=mox.IgnoreArg()
                                           ).AndRaise(socket.error())
        self.mock.ReplayAll()
        try:
            client.raw_request('GET', '/v1/images/detail?limit=20')

            self.fail('An exception should have bypassed this line.')
        except exc.CommunicationError as comm_err:
            fail_msg = ("Exception message '%s' should contain '%s'" %
                        (comm_err.message, endpoint))
            self.assertTrue(endpoint in comm_err.message, fail_msg)

    def test_parse_endpoint(self):
        endpoint = 'http://example.com:9292'
        test_client = http.HTTPClient(endpoint, token=u'adc123')
        actual = test_client.parse_endpoint(endpoint)
        expected = parse.ParseResult(scheme='http',
                                     netloc='example.com:9292', path='',
                                     params='', query='', fragment='')
        self.assertEqual(expected, actual)

    def test_get_connection_class(self):
        endpoint = 'http://example.com:9292'
        test_client = http.HTTPClient(endpoint, token=u'adc123')
        actual = (test_client.get_connection_class('https'))
        self.assertEqual(actual, http.VerifiedHTTPSConnection)

    def test_get_connections_kwargs_http(self):
        endpoint = 'http://example.com:9292'
        test_client = http.HTTPClient(endpoint, token=u'adc123')
        actual = test_client.get_connection_kwargs('http', insecure=True)
        self.assertEqual({'timeout': 600.0}, actual)

    def test_get_connections_kwargs_https(self):
        endpoint = 'http://example.com:9292'
        test_client = http.HTTPClient(endpoint, token=u'adc123')
        actual = test_client.get_connection_kwargs('https', insecure=True)
        expected = {'cacert': None,
                    'cert_file': None,
                    'insecure': True,
                    'key_file': None,
                    'ssl_compression': True,
                    'timeout': 600.0}
        self.assertEqual(expected, actual)


class TestHostResolutionError(testtools.TestCase):

    def setUp(self):
        super(TestHostResolutionError, self).setUp()
        self.mock = mox.Mox()
        self.invalid_host = "example.com.incorrect_top_level_domain"

    def test_incorrect_domain_error(self):
        """
        Make sure that using a domain which does not resolve causes an
        exception which mentions that specific hostname as a reason for
        failure.
        """
        class FailingConnectionClass(object):
            def __init__(self, *args, **kwargs):
                pass

            def putrequest(self, *args, **kwargs):
                raise socket.gaierror(-2, "Name or service not known")

            def request(self, *args, **kwargs):
                raise socket.gaierror(-2, "Name or service not known")

        self.endpoint = 'http://%s:9292' % (self.invalid_host,)
        self.client = http.HTTPClient(self.endpoint, token=u'abc123')

        self.mock.StubOutWithMock(self.client, 'get_connection')
        self.client.get_connection().AndReturn(FailingConnectionClass())
        self.mock.ReplayAll()

        try:
            self.client.raw_request('GET', '/example/path')
            self.fail("gaierror should be raised")
        except exc.InvalidEndpoint as e:
            self.assertTrue(self.invalid_host in str(e),
                            "exception should contain the hostname")

    def tearDown(self):
        super(TestHostResolutionError, self).tearDown()
        self.mock.UnsetStubs()


class TestVerifiedHTTPSConnection(testtools.TestCase):
    """Test fixture for glanceclient.common.http.VerifiedHTTPSConnection."""

    def test_setcontext_unable_to_load_cacert(self):
        """Add this UT case with Bug#1265730."""
        self.assertRaises(exc.SSLConfigurationError,
                          http.VerifiedHTTPSConnection,
                          "127.0.0.1",
                          None,
                          None,
                          None,
                          "gx_cacert",
                          None,
                          False,
                          True)


class TestResponseBodyIterator(testtools.TestCase):

    def test_iter_default_chunk_size_64k(self):
        resp = utils.FakeResponse({}, six.StringIO('X' * 98304))
        iterator = http.ResponseBodyIterator(resp)
        chunks = list(iterator)
        self.assertEqual(chunks, ['X' * 65536, 'X' * 32768])

    def test_integrity_check_with_correct_checksum(self):
        resp = utils.FakeResponse({}, six.StringIO('CCC'))
        body = http.ResponseBodyIterator(resp)
        body.set_checksum('defb99e69a9f1f6e06f15006b1f166ae')
        list(body)

    def test_integrity_check_with_wrong_checksum(self):
        resp = utils.FakeResponse({}, six.StringIO('BB'))
        body = http.ResponseBodyIterator(resp)
        body.set_checksum('wrong')
        try:
            list(body)
            self.fail('integrity checked passed with wrong checksum')
        except IOError as e:
            self.assertEqual(errno.EPIPE, e.errno)

    def test_set_checksum_in_consumed_iterator(self):
        resp = utils.FakeResponse({}, six.StringIO('CCC'))
        body = http.ResponseBodyIterator(resp)
        list(body)
        # Setting checksum for an already consumed iterator should raise an
        # AttributeError.
        self.assertRaises(
            AttributeError, body.set_checksum,
            'defb99e69a9f1f6e06f15006b1f166ae')

    def test_body_size(self):
        size = 1000000007
        resp = utils.FakeResponse(
            {'content-length': str(size)}, six.StringIO('BB'))
        body = http.ResponseBodyIterator(resp)
        self.assertEqual(len(body), size)
