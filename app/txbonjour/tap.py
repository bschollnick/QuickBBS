""" A standard twisted tap file for an exposed service for txbonjour"""

from zope.interface import implements, implementer
from twisted.python import log, usage
from twisted.plugin import IPlugin
from twisted.internet import reactor
from twisted.application.service import IServiceMaker, MultiService

from txbonjour import version, name, description, service, discovery


class LoggingProtocol(discovery.BroadcastProtocol):
    """ I am a logging protocol. I do nothing but log what I receive. """

    def registerReceived(self, *args):
        log.msg('now broadcasting: %r' % (args,))

    def addService(self, *args):
        log.msg('add service: %r' % (args,))

    def removeService(self, *args):
        log.msg('remove service: %r' % (args,))

    def browseError(self, *args):
        log.msg('browseError: %r' % (args,))

    def resolveError(self, err, *args):
        log.msg('resolveError: %s - %r' % (err, args,))


class Options(usage.Options):

    optFlags = [
        ['resolve-domains', 'n', 'Resolve FQDM to ip addresses before '\
                                    'reporting']
    ]
    optParameters = [
        ['port', 'p', 9898, 'The port to broadcast to bonjour clients to '\
                            'connect to you', int],
        ['registration', 'r', '_examples._tcp', 'The mDNS registry for bonjour'\
                                                ', ie. <domain>.<transport>'],
        ['service-name', 's', 'Example-Service', 'The name bonjour clients '\
                                                    'will see for your service'],
    ]


class ServiceMaker(object):
    
    implements(IServiceMaker, IPlugin)
    
    tapname = 'txbonjour'
    description = description
    version = version
    options = Options

    def makeService(self, options,
                    broadcast_protocol=None,
                    discovery_protocol=None):
        """ Accepts options as a regular twistd plugin does. Also accepts
            keyword arguments 'broadcast_protocol' for a procotcol *instance*
            and 'discovery_protocol' for a protocol *instance*. Returns a
            twisted.application.service.IService implementor.

        """
        service_name = options.get('service-name')
        resolve = options.get('resolve-domains')
        port = options.get('port')
        registry = options.get('registration')
        service_name = options.get('service-name')

        s = MultiService()
        s.setName('txbonjour-%s' % (service_name,))

        logging_proto = LoggingProtocol()

        if broadcast_protocol is None:
            broadcast_protocol = logging_proto

        if discovery_protocol is None:
            discovery_protocol = logging_proto

        discover_service = discovery.listenBonjour(discovery_protocol,
                                                   registry,
                                                   resolve_ips=resolve,
                                                   )
        discover_service.setName('discovery')
        discover_service.setServiceParent(s)
        
        def broadcast():
            broadcast_service = discovery.connectBonjour(broadcast_protocol,
                                                         registry,
                                                         port,
                                                         service_name,
                                                         )
            broadcast_service.setName('broadcast')
            broadcast_service.setServiceParent(s)
            
        reactor.callWhenRunning(broadcast)
        return s


serviceMaker = ServiceMaker()
makeService = serviceMaker.makeService
