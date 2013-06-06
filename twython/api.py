# -*- coding: utf-8 -*-

"""
twython.api
~~~~~~~~~~~

This module contains functionality for access to core Twitter API calls,
Twitter Authentication, and miscellaneous methods that are useful when
dealing with the Twitter API
"""

import requests
from requests_oauthlib import OAuth1

from . import __version__
from .compat import json, urlencode, parse_qsl, quote_plus, str, is_py2
from .endpoints import EndpointsMixin
from .exceptions import TwythonError, TwythonAuthError, TwythonRateLimitError
from .helpers import _transparent_params


class Twython(EndpointsMixin, object):
    def __init__(self, app_key=None, app_secret=None, oauth_token=None,
                 oauth_token_secret=None, headers=None, proxies=None,
                 api_version='1.1', ssl_verify=True):
        """Instantiates an instance of Twython. Takes optional parameters for authentication and such (see below).

        :param app_key: (optional) Your applications key
        :param app_secret: (optional) Your applications secret key
        :param oauth_token: (optional) Used with oauth_token_secret to make authenticated calls
        :param oauth_token_secret: (optional) Used with oauth_token to make authenticated calls
        :param headers: (optional) Custom headers to send along with the request
        :param proxies: (optional) A dictionary of proxies, for example {"http":"proxy.example.org:8080", "https":"proxy.example.org:8081"}.
        :param ssl_verify: (optional) Turns off ssl verification when False. Useful if you have development server issues.

        """

        # API urls, OAuth urls and API version; needed for hitting that there API.
        self.api_version = api_version
        self.api_url = 'https://api.twitter.com/%s'
        self.request_token_url = self.api_url % 'oauth/request_token'
        self.access_token_url = self.api_url % 'oauth/access_token'
        self.authenticate_url = self.api_url % 'oauth/authenticate'

        self.app_key = app_key
        self.app_secret = app_secret
        self.oauth_token = oauth_token
        self.oauth_token_secret = oauth_token_secret

        req_headers = {'User-Agent': 'Twython v' + __version__}
        if headers:
            req_headers.update(headers)

        # Generate OAuth authentication object for the request
        # If no keys/tokens are passed to __init__, auth=None allows for
        # unauthenticated requests, although I think all v1.1 requests need auth
        auth = None
        if self.app_key is not None and self.app_secret is not None and \
           self.oauth_token is None and self.oauth_token_secret is None:
            auth = OAuth1(self.app_key, self.app_secret)

        if self.app_key is not None and self.app_secret is not None and \
           self.oauth_token is not None and self.oauth_token_secret is not None:
            auth = OAuth1(self.app_key, self.app_secret,
                          self.oauth_token, self.oauth_token_secret)

        self.client = requests.Session()
        self.client.headers = req_headers
        self.client.proxies = proxies
        self.client.auth = auth
        self.client.verify = ssl_verify

        self._last_call = None

    def __repr__(self):
        return '<Twython: %s>' % (self.app_key)

    def _request(self, url, method='GET', params=None, api_call=None):
        """Internal request method"""
        method = method.lower()
        params = params or {}

        func = getattr(self.client, method)
        params, files = _transparent_params(params)
        if method == 'get':
            response = func(url, params=params)
        else:
            response = func(url, data=params, files=files)
        content = response.content.decode('utf-8')

        # create stash for last function intel
        self._last_call = {
            'api_call': api_call,
            'api_error': None,
            'cookies': response.cookies,
            'headers': response.headers,
            'status_code': response.status_code,
            'url': response.url,
            'content': content,
        }

        #  Wrap the json loads in a try, and defer an error
        #  Twitter will return invalid json with an error code in the headers
        json_error = False
        try:
            try:
                # try to get json
                content = content.json()
            except AttributeError:
                # if unicode detected
                content = json.loads(content)
        except ValueError:
            json_error = True
            content = {}

        if response.status_code > 304:
            # If there is no error message, use a default.
            errors = content.get('errors',
                                 [{'message': 'An error occurred processing your request.'}])
            if errors and isinstance(errors, list):
                error_message = errors[0]['message']
            else:
                error_message = errors
            self._last_call['api_error'] = error_message

            ExceptionType = TwythonError
            if response.status_code == 429:
                # Twitter API 1.1, always return 429 when rate limit is exceeded
                ExceptionType = TwythonRateLimitError
            elif response.status_code == 401 or 'Bad Authentication data' in error_message:
                # Twitter API 1.1, returns a 401 Unauthorized or
                # a 400 "Bad Authentication data" for invalid/expired app keys/user tokens
                ExceptionType = TwythonAuthError

            raise ExceptionType(error_message,
                                error_code=response.status_code,
                                retry_after=response.headers.get('retry-after'))

        # if we have a json error here, then it's not an official Twitter API error
        if json_error and not response.status_code in (200, 201, 202):
            raise TwythonError('Response was not valid JSON, unable to decode.')

        return content

    def request(self, endpoint, method='GET', params=None, version='1.1'):
        """Return dict of response received from Twitter's API

        :param endpoint: (required) Full url or Twitter API endpoint (e.g. search/tweets)
        :type endpoint: string
        :param method: (optional) Method of accessing data, either GET or POST. (default GET)
        :type method: string
        :param params: (optional) Dict of parameters (if any) accepted the by Twitter API endpoint you are trying to access (default None)
        :type params: dict or None
        :param version: (optional) Twitter API version to access (default 1.1)
        :type version: string

        :rtype: dict
        """

        # In case they want to pass a full Twitter URL
        # i.e. https://api.twitter.com/1.1/search/tweets.json
        if endpoint.startswith('http://') or endpoint.startswith('https://'):
            url = endpoint
        else:
            url = '%s/%s.json' % (self.api_url % version, endpoint)

        content = self._request(url, method=method, params=params, api_call=url)

        return content

    def get(self, endpoint, params=None, version='1.1'):
        """Shortcut for GET requests via :class:`request`"""
        return self.request(endpoint, params=params, version=version)

    def post(self, endpoint, params=None, version='1.1'):
        """Shortcut for POST requests via :class:`request`"""
        return self.request(endpoint, 'POST', params=params, version=version)

    def get_lastfunction_header(self, header):
        """Returns a specific header from the last API call
        This will return None if the header is not present

        :param header: (required) The name of the header you want to get the value of

        Most useful for the following header information:
            x-rate-limit-limit,
            x-rate-limit-remaining,
            x-rate-limit-class,
            x-rate-limit-reset

        """
        if self._last_call is None:
            raise TwythonError('This function must be called after an API call.  It delivers header information.')

        if header in self._last_call['headers']:
            return self._last_call['headers'][header]
        else:
            return None

    def get_authentication_tokens(self, callback_url=None, force_login=False, screen_name=''):
        """Returns a dict including an authorization URL, ``auth_url``, to direct a user to

        :param callback_url: (optional) Url the user is returned to after they authorize your app (web clients only)
        :param force_login: (optional) Forces the user to enter their credentials to ensure the correct users account is authorized.
        :param app_secret: (optional) If forced_login is set OR user is not currently logged in, Prefills the username input box of the OAuth login screen with the given value
        :rtype: dict
        """
        callback_url = callback_url or self.callback_url
        request_args = {}
        if callback_url:
            request_args['oauth_callback'] = callback_url
        response = self.client.get(self.request_token_url, params=request_args)

        if response.status_code == 401:
            raise TwythonAuthError(response.content, error_code=response.status_code)
        elif response.status_code != 200:
            raise TwythonError(response.content, error_code=response.status_code)

        request_tokens = dict(parse_qsl(response.content.decode('utf-8')))
        if not request_tokens:
            raise TwythonError('Unable to decode request tokens.')

        oauth_callback_confirmed = request_tokens.get('oauth_callback_confirmed') == 'true'

        auth_url_params = {
            'oauth_token': request_tokens['oauth_token'],
        }

        if force_login:
            auth_url_params.update({
                'force_login': force_login,
                'screen_name': screen_name
            })

        # Use old-style callback argument if server didn't accept new-style
        if callback_url and not oauth_callback_confirmed:
            auth_url_params['oauth_callback'] = self.callback_url

        request_tokens['auth_url'] = self.authenticate_url + '?' + urlencode(auth_url_params)

        return request_tokens

    def get_authorized_tokens(self, oauth_verifier):
        """Returns a dict of authorized tokens after they go through the :class:`get_authentication_tokens` phase.

        :param oauth_verifier: (required) The oauth_verifier (or a.k.a PIN for non web apps) retrieved from the callback url querystring
        :rtype: dict

        """
        response = self.client.get(self.access_token_url, params={'oauth_verifier': oauth_verifier})
        authorized_tokens = dict(parse_qsl(response.content.decode('utf-8')))
        if not authorized_tokens:
            raise TwythonError('Unable to decode authorized tokens.')

        return authorized_tokens

    # ------------------------------------------------------------------------------------------------------------------------
    # The following methods are all different in some manner or require special attention with regards to the Twitter API.
    # Because of this, we keep them separate from all the other endpoint definitions - ideally this should be change-able,
    # but it's not high on the priority list at the moment.
    # ------------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def construct_api_url(api_url, **params):
        """Construct a Twitter API url, encoded, with parameters

        :param api_url: URL of the Twitter API endpoint you are attempting to construct
        :param \*\*params: Parameters that are accepted by Twitter for the endpoint you're requesting
        :rtype: string

        Usage::

          >>> from twython import Twython
          >>> twitter = Twython()

          >>> api_url = 'https://api.twitter.com/1.1/search/tweets.json'
          >>> constructed_url = twitter.construct_api_url(api_url, q='python', result_type='popular')
          >>> print constructed_url
          https://api.twitter.com/1.1/search/tweets.json?q=python&result_type=popular

        """
        querystring = []
        params, _ = _transparent_params(params or {})
        params = requests.utils.to_key_val_list(params)
        for (k, v) in params:
            querystring.append(
                '%s=%s' % (Twython.encode(k), quote_plus(Twython.encode(v)))
            )
        return '%s?%s' % (api_url, '&'.join(querystring))

    def search_gen(self, search_query, **params):
        """Returns a generator of tweets that match a specified query.

        Documentation: https://dev.twitter.com/docs/api/1.1/get/search/tweets

        :param search_query: Query you intend to search Twitter for
        :param \*\*params: Extra parameters to send with your search request
        :rtype: generator

        Usage::

          >>> from twython import Twython
          >>> twitter = Twython(APP_KEY, APP_SECRET, OAUTH_TOKEN, OAUTH_TOKEN_SECRET)

          >>> search = twitter.search_gen('python')
          >>> for result in search:
          >>>   print result

        """
        content = self.search(q=search_query, **params)

        if not content.get('statuses'):
            raise StopIteration

        for tweet in content['statuses']:
            yield tweet

        try:
            if not 'since_id' in params:
                params['since_id'] = (int(content['statuses'][0]['id_str']) + 1)
        except (TypeError, ValueError):
            raise TwythonError('Unable to generate next page of search results, `page` is not a number.')

        for tweet in self.search_gen(search_query, **params):
            yield tweet

    @staticmethod
    def unicode2utf8(text):
        try:
            if is_py2 and isinstance(text, str):
                text = text.encode('utf-8')
        except:
            pass
        return text

    @staticmethod
    def encode(text):
        if is_py2 and isinstance(text, (str)):
            return Twython.unicode2utf8(text)
        return str(text)