# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
This example shows how to make simple web authentication.

To run the example:
    $ python webguard.py

When you visit http://127.0.0.1:8889/, the page will ask for an username &
password. See the code in main() to get the correct username & password!

http://twistedmatrix.com/documents/8.1.0/api/twisted.cred.checkers.FilePasswordDB.html

http://www.htaccesstools.com/htpasswd-generator/

testuser & testpassword = testuser:$apr1$LgHQMxj9$9Y59Q451UddeLhhoAdsfN1

"""

import sys

from zope.interface import implements

from twisted.python import log
from twisted.internet import reactor
from twisted.web import server, resource, guard
from twisted.cred.portal import IRealm, Portal
from twisted.cred.checkers import FilePasswordDB

import crypt
import md5
import os, os.path

from passlib.apache import HtpasswdFile
htpasswdfile = HtpasswdFile(os.path.join(os.path.abspath("."), "htpasswd"))

class GuardedResource(resource.Resource):
    """
    A resource which is protected by guard and requires authentication in order
    to access.
    """
    def getChild(self, path, request):
        return self

    def render(self, request):
        return "Authorized!"


class SimpleRealm(object):
    """
    A realm which gives out L{GuardedResource} instances for authenticated
    users.
    """
    implements(IRealm)

    def requestAvatar(self, avatarId, mind, *interfaces):
        if resource.IResource in interfaces:
            return resource.IResource, GuardedResource(), lambda: None
        raise NotImplementedError()

def cmp_pass(uname, password, storedpass):
    print storedpass, storedpass[:-2]
    print "md5 hex: ",md5.md5(password).hexdigest()
    print "password : ", password
    print "stored : ", storedpass
    #print crypt.crypt(password, storedpass)
#    return crypt.crypt(password, storedpass)
    print  htpasswd.check_password(username, password)


def main():
    log.startLogging(sys.stdout)
    # add in the path to your .htpasswd in place of path_to_htpasswd
    checkers = [FilePasswordDB(htpasswdfile, hash=cmp_pass)]
    wrapper = guard.HTTPAuthSessionWrapper(
                    Portal(SimpleRealm(), checkers),
                    [guard.BasicCredentialFactory('yoursite.com')])
    reactor.listenTCP(8080, server.Site(resource = wrapper))
    reactor.run()

if __name__ == '__main__':
    main()
