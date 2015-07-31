"""
#
# Login Page logic using Twisted sessions
#
# Defines two functions used like before filters
#   current_user(reqeust) - return the username or ""
#   require_login(request) - go to login page if not logged in
#
# LoginResource()
# LogoutResource()
# IndexResource({ dict })
#
"""
import cgi
import common
import config
import gallery
import os
import os.path
import random

from twisted.web.server import Site, NOT_DONE_YET
from twisted.web import static
from twisted.web.resource import Resource
from twisted.internet import reactor

from twisted.web.server import Session
from twisted.python import log
from twisted.python.logfile import LogFile

from jinja2 import Environment, FileSystemLoader

##############################################################################
def require_login(request):
    """
    User Session data
    """
    urlref = request.path
    print "REQUIRE_LOGIN:%s" % urlref

    session = request.getSession()
    login = gallery.ILoginSessionData(session)
    login.urlref = urlref
    #
    #   Force user to login
    #
    request.redirect("/login")
    request.finish()
    return NOT_DONE_YET

##############################################################################
class LoginPage(Resource):

    """
    Login Page with Guard

    Login page includes the username / password form.
    If successfully logged in, redirected to the index.html page.
    """

    def __init__(self, ctx, env, htpasswd):
        self.ctx = ctx
        self.env = env
        self.htpasswd = htpasswd
##############################################################################
    def render_GET(self, request):
        """
        Render the Login page
        """
        session = request.getSession()
        login = gallery.ILoginSessionData(session)
        login.csrf = str(random.randint(0, 1000000))
        self.ctx = {'_csrf': login.csrf}
        template = self.env.get_template("login_greeting.html")
        return str(template.render(self.ctx))
##############################################################################
    def onResult(self, username, request, success):
        """
        Tests for a successfully username / password match in the htpasswd
        file.

        uses the passlib library for the htpassword file.

        If there is a match, redirect to the index.html page (menu)
        If failure, redirect / reload the login page.
        """
        if success:
            session = request.getSession()
            login = gallery.ILoginSessionData(session)
            login.username = username
            # retrieve from session and reset
            urlref = login.urlref
            login.urlref = ""

            log.msg("Username %s Successfully Logged in." % username)

            if urlref:
                log.msg("Redirecting to %s" % urlref)
                request.redirect(urlref)
                request.finish()
            else:
                log.msg("Sent to Index Page")
                request.write("""<html><body>
                You are now logged in as %s
                </body></html>
                    """ % username)
                request.redirect("/index")
                request.finish()
        else:
            log.msg("User %s NOT successfully logged in." % username)
            request.redirect("/login")
            request.finish()
##############################################################################
    def render_POST(self, request):
        """
        Receives the login page post data, extracts it, verifies
        the csrf, and then hands off to onResult for testing
        the username / password.
        """
        session = request.getSession()
        login = gallery.ILoginSessionData(session)

        # retrieve from post data
        username = cgi.escape(request.args["username"][0],)
        password = cgi.escape(request.args["password"][0],)
        csrf = cgi.escape(request.args["_csrf"][0],)

        log.msg("POST csrf:%s username:%s password:%s" %
                (csrf, username, password))

        if csrf != login.csrf:
            log.msg("CSRF ATTACK!")
            request.redirect("/login")
            request.finish()
            return NOT_DONE_YET

        self.onResult(
            username, request, self.htpasswd.check_password(username, password))
        return NOT_DONE_YET
##############################################################################
class LogoutPage(Resource):
    """
    Log the user out
    """
    def __init__(self, ctx, env, htpasswd):
        self.ctx = ctx
        self.env = env
        self.htpasswd = htpasswd
##############################################################################
    def render_GET(self, request):
        """
        Force the session to expire, and redirect to the logout page.
        """
        request.getSession().expire()

        self.ctx = {}
        template = self.env.get_template("logout_greeting.html")
        return str(template.render(self.ctx))
##############################################################################
class IndexPage(Resource):
    """
    Log the user out
    """
    isLeaf = True
##############################################################################
    def __init__(self, ctx, env):
        """
        Log the user out
        """
        self.ctx = ctx
        self.env = env
        Resource.__init__(self)
##############################################################################
    def render_GET(self, request):
        """
        Log the user out
        """
        session = request.getSession()
        login = gallery.ILoginSessionData(session)

        if config.SETTINGS["require_login"] != 0:
            if not login.username or login.username == "":
                # this should store the current path, render the login page, and
                # finally redirect back here
                return require_login(request)

        # add the user to the context
        #ctx = self.ctx.copy()
        self.ctx['username'] = login.username
        self.ctx['sort_order'] = login.sort_order
        self.ctx["page_data"] = {}
        template = self.env.get_template("index.html")
        return str(template.render(self.ctx))

##############################################################################
class RootPage(Resource):
    """
    Log the user out
    """
#
# The root page usually wants to redirect to somewhere else
#
##############################################################################
    def render_GET(self, request):
        """
        Log the user out
        """
        log.msg("ROOT REDIRECT")
        request.redirect("/index")
        request.finish()
        return NOT_DONE_YET
##############################################################################
def main():
    """
    Run the server
    """
    config.load_config_data()

    ##############################################################################
    class ShortSession(Session):
        """
        Increase the session timeout
        """
        sessionTimeout = config.SETTINGS["session_logout_timeout"]
    ##############################################################################

#     def handler(signum, frame):
#         print "Shutting down, due to kill request."
#         print "Signal handler called with signal", signum
#         reactor.stop()
#
#     signal.signal(signal.SIGHUP, handler)
#     signal.signal(signal.SIGTERM, handler)
#     signal.signal(signal.SIGINT, handler)
#     signal.signal(signal.SIGQUIT, handler)
#     signal.signal(signal.SIGABRT, handler)
#     for location in config.LOCATIONS.keys():
#         print "%s Root : %s" % (location, config.LOCATIONS[location])

    env = Environment(loader=FileSystemLoader(
        config.LOCATIONS["templates_root"]))

    log_path = os.path.abspath(config.LOCATIONS["server_log"])
    if common.assure_path_exists(log_path):
        print "Creating Log File Path"

    log.startLogging(LogFile.fromFullPath(log_path,
                                          maxRotatedFiles=10),
                     setStdout=False)

    ctx = {}

    root = Resource()

    if config.SETTINGS["require_login"] != 0:
        from passlib.apache import HtpasswdFile
        htpasswd = HtpasswdFile(
            os.path.join(config.LOCATIONS["config_root"],
                         "gallery.passwdfile"))
        root.putChild("login", LoginPage(ctx, env, htpasswd))
        root.putChild("logout", LogoutPage(ctx, env, htpasswd))
    else:
        root.putChild("login", RootPage())
        root.putChild("logout", RootPage())

    root.putChild("", RootPage())
    root.putChild("index", IndexPage(ctx, env))

    root.putChild("javascript",
                  static.File(config.LOCATIONS["javascript_root"],
                              "application/javascript"))
    root.putChild("css", static.File(config.LOCATIONS["css_root"]))
    root.putChild("fonts", static.File(config.LOCATIONS["fonts_root"]))
    root.putChild("thumbnails",
                  static.File(config.LOCATIONS["thumbnails_root"]))
    root.putChild("images", static.File(config.LOCATIONS["images_root"]))
    root.putChild("albums", gallery.Gallery(ctx, env, log))

    if config.SETTINGS["use_bonjour"] == "1":
        from txbonjour import discovery
        print "Starting Bonjour Services"
        proto = discovery.BroadcastProtocol()
        discovery.connectBonjour(proto,
                                 '_http._tcp',
                                 config.SETTINGS["server_port"],
                                 'DAAP Server')

    factory = Site(root)
    factory.sessionFactory = ShortSession
# http://twistedmatrix.com/documents/14.0.0/web/
#       howto/web-in-60/session-endings.html
    print "Listening on Port %s..." % config.SETTINGS["server_port"]
    reactor.suggestThreadPoolSize(5)
    reactor.listenTCP(config.SETTINGS["server_port"], factory)
    #reactor.run(installSignalHandlers=False)
    reactor.run()

if __name__ == "__main__":
    main()
