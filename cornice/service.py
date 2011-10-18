# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Sync Server
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Tarek Ziade (tarek@mozilla.com)
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****
import os

from webob.exc import HTTPNotFound, HTTPMethodNotAllowed

from pyramid.config import Configurator
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.view import view_config
from pyramid.events import BeforeRender

import venusian

from cornice.resources import Root
from cornice.config import Config
from cornice import util


def add_renderer_globals(event):
    event['util'] = util


def add_apidoc(config, pattern, docstring, renderer):
    apidocs = config.registry.settings.setdefault('apidocs', {})
    info = apidocs.setdefault(pattern, {})
    info['docstring'] = docstring
    info['renderer'] = renderer


_SERVICES = {}


def _notfound(request):
    match = request.matchdict
    # the route exists, raising a 405
    if match is not None:
        pattern = request.matched_route.pattern
        if pattern in _SERVICES:

            service = _SERVICES[pattern]
            res = HTTPMethodNotAllowed()
            res.allow = service.defined_methods
            return res

    # 404
    return HTTPNotFound()


class Service(object):
    def __init__(self, **kw):
        self.route_pattern = kw.pop('path')
        if self.route_pattern in _SERVICES:
            raise ValueError('%r already defined' % self.route_pattern)
        self.defined_methods = []
        self.route_name = self.route_pattern
        self.renderer = kw.pop('renderer', 'json')
        self.kw = kw
        _SERVICES[self.route_pattern] = self
        self._defined = False

    def _define(self, config, method):
        # registring the method
        if method not in self.defined_methods:
            self.defined_methods.append(method)

        if not self._defined:
            # defining the route
            config.add_route(self.route_name, self.route_pattern)
            self._defined = True

    def api(self, **kw):
        method = kw.get('request_method', 'GET')
        api_kw = {}
        api_kw.update(kw)

        if 'renderer' not in api_kw:
            api_kw['renderer'] = self.renderer

        def _api(func):
            _api_kw = api_kw.copy()
            docstring = func.__doc__

            def callback(context, name, ob):
                config = context.config.with_package(info.module)
                self._define(config, method)
                config.add_apidoc((self.route_pattern, method),
                                   docstring, self.renderer)
                config.add_view(view=ob, route_name=self.route_name,
                                **_api_kw)

            info = venusian.attach(func, callback, category='pyramid')

            if info.scope == 'class':
                # if the decorator was attached to a method in a class, or
                # otherwise executed at class scope, we need to set an
                # 'attr' into the settings if one isn't already in there
                if 'attr' not in kw:
                    kw['attr'] = func.__name__

            kw['_info'] = info.codeinfo   # fbo "action_method"
            return func
        return _api


@view_config(route_name='apidocs', renderer='apidocs.mako')
def apidocs(request):
    routes = []
    for k, v in request.registry.settings['apidocs'].items():
        routes.append((k, v))
    return {'routes': routes}


HERE = os.path.dirname(__file__)


def get_config(request):
    return request.registry.settings.get('config')


def heartbeat(request):
    # checks the server's state -- if wrong, return a 503 here
    return 'OK'


def manage(request):
    ## if it's not a local call, this does not exist

    # XXX protect with new auth APIs
    #if not is_local(request):
    #    raise HTTPNotFound()

    # now let's see if the config allows the debug mode
    config = get_config(request)
    if (not config.has_option('global', 'debug') or
        not config.get('global', 'debug')):
        raise HTTPNotFound()

    # local + activated
    return {'config': config}


def main(package=None):
    def _main(global_config, **settings):
        config_file = global_config['__file__']
        config_file = os.path.abspath(
                        os.path.normpath(
                        os.path.expandvars(
                            os.path.expanduser(
                            config_file))))

        settings['config'] = config = Config(config_file)
        conf_dir, _ = os.path.split(config_file)

        authz_policy = ACLAuthorizationPolicy()
        config = Configurator(root_factory=Root, settings=settings,
                              authorization_policy=authz_policy)

        # add auth via repoze.who
        # eventually the app will have to do this explicitly
        config.include("cornice.auth.whoauth")

        # adding default views: __heartbeat__, __apis__
        config.add_route('heartbeat', '/__heartbeat__',
                        renderer='string',
                        view='cornice.service.heartbeat')

        config.add_route('manage', '/__config__',
                        renderer='config.mako',
                        view='cornice.service.manage')

        config.add_static_view('static', 'cornice:static', cache_max_age=3600)
        config.add_directive('add_apidoc', add_apidoc)
        config.add_route('apidocs', '/__apidocs__')
        config.add_view(_notfound, context=HTTPNotFound)
        config.add_subscriber(add_renderer_globals, BeforeRender)
        config.scan()
        config.scan(package=package)
        return config.make_wsgi_app()
    return _main


def make_main(package=None):
    """Factory to build apps."""
    return main(package)
